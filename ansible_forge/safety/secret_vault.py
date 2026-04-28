"""Per-session in-memory secret vault — secrets never leave the backend."""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

REDACTION_PLACEHOLDER = "<<SECRET:{name}>>"
_SECRET_MIN_LENGTH = 6


@dataclass
class SecretEntry:
    """Metadata for a stored secret. The value itself is only held in _value."""

    name: str
    description: str
    created_at: float = field(default_factory=time.time)
    _value: str = field(repr=False, default="")

    @property
    def value(self) -> str:
        return self._value

    def __str__(self) -> str:
        return f"SecretEntry(name={self.name!r}, description={self.description!r})"

    def __repr__(self) -> str:
        return self.__str__()


class SessionVault:
    """Holds secrets for a single session."""

    def __init__(self, session_id: str, ttl_seconds: float = 7200) -> None:
        self._session_id = session_id
        self._secrets: dict[str, SecretEntry] = {}
        self._ttl = ttl_seconds
        self._pending: dict[str, asyncio.Event] = {}

    def store(self, name: str, value: str, description: str = "") -> None:
        self._secrets[name] = SecretEntry(
            name=name, description=description, _value=value
        )
        if name in self._pending:
            self._pending[name].set()
        logger.info("secret_stored", session_id=self._session_id, name=name)

    def get(self, name: str) -> str | None:
        entry = self._secrets.get(name)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            self._secrets.pop(name, None)
            logger.info("secret_expired", session_id=self._session_id, name=name)
            return None
        return entry.value

    def list_names(self) -> list[dict[str, str]]:
        self._evict_expired()
        return [
            {"name": e.name, "description": e.description}
            for e in self._secrets.values()
        ]

    def get_all(self) -> dict[str, str]:
        """Return all non-expired secrets as {name: value} for injection."""
        self._evict_expired()
        return {name: e.value for name, e in self._secrets.items()}

    def delete(self, name: str) -> bool:
        removed = self._secrets.pop(name, None)
        return removed is not None

    def clear(self) -> None:
        self._secrets.clear()

    def create_pending(self, name: str) -> asyncio.Event:
        evt = asyncio.Event()
        self._pending[name] = evt
        return evt

    def cleanup_pending(self, name: str) -> None:
        self._pending.pop(name, None)

    def redact(self, text: str) -> str:
        """Replace any known secret value in *text* with its placeholder."""
        self._evict_expired()
        for name, entry in self._secrets.items():
            val = entry.value
            if len(val) < _SECRET_MIN_LENGTH:
                continue
            if val in text:
                text = text.replace(val, REDACTION_PLACEHOLDER.format(name=name))
        return text

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        """Deep-redact all string values in a dict."""
        return _redact_recursive(data, self.redact)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [n for n, e in self._secrets.items() if now - e.created_at > self._ttl]
        for n in expired:
            self._secrets.pop(n, None)

    def __repr__(self) -> str:
        return f"SessionVault(session={self._session_id!r}, secrets={list(self._secrets.keys())})"


class SecretVault:
    """Global vault — holds per-session vaults. Thread-safe via asyncio."""

    _instance: SecretVault | None = None

    def __init__(self, default_ttl: float = 7200) -> None:
        self._sessions: dict[str, SessionVault] = {}
        self._default_ttl = default_ttl

    @classmethod
    def get_instance(cls) -> SecretVault:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def for_session(self, session_id: str) -> SessionVault:
        if session_id not in self._sessions:
            self._sessions[session_id] = SessionVault(session_id, self._default_ttl)
        return self._sessions[session_id]

    def destroy_session(self, session_id: str) -> None:
        vault = self._sessions.pop(session_id, None)
        if vault:
            vault.clear()

    def __repr__(self) -> str:
        return f"SecretVault(sessions={list(self._sessions.keys())})"


def _redact_recursive(obj: Any, redact_fn: Any) -> Any:
    """Recursively redact string values in nested dicts/lists."""
    if isinstance(obj, str):
        return redact_fn(obj)
    if isinstance(obj, dict):
        return {k: _redact_recursive(v, redact_fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_recursive(i, redact_fn) for i in obj]
    return obj


def build_secret_pattern(vault: SessionVault) -> re.Pattern[str] | None:
    """Build a compiled regex that matches any stored secret value."""
    values = [re.escape(e.value) for e in vault._secrets.values() if len(e.value) >= _SECRET_MIN_LENGTH]
    if not values:
        return None
    return re.compile("|".join(values))
