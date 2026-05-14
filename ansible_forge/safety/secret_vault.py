"""Per-session secret vault with encrypted persistence across restarts."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

REDACTION_PLACEHOLDER = "<<SECRET:{name}>>"
_SECRET_MIN_LENGTH = 6
_VAULT_DIR = Path.home() / ".ansibleforge" / "vault"
_KEY_FILE = _VAULT_DIR / ".key"


def _get_or_create_key() -> bytes:
    _VAULT_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        return _KEY_FILE.read_bytes()
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)
    os.chmod(_KEY_FILE, 0o600)
    return key


def _encrypt(data: str) -> bytes:
    from cryptography.fernet import Fernet
    return Fernet(_get_or_create_key()).encrypt(data.encode())


def _decrypt(token: bytes) -> str:
    from cryptography.fernet import Fernet
    return Fernet(_get_or_create_key()).decrypt(token).decode()


@dataclass
class SecretEntry:
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
    """Holds secrets for a single session with encrypted disk persistence."""

    def __init__(self, session_id: str, ttl_seconds: float = 7200) -> None:
        self._session_id = session_id
        self._secrets: dict[str, SecretEntry] = {}
        self._ttl = ttl_seconds
        self._pending: dict[str, asyncio.Event] = {}
        self._load_from_disk()

    def _disk_path(self) -> Path:
        return _VAULT_DIR / f"{self._session_id}.enc"

    def _save_to_disk(self) -> None:
        try:
            _VAULT_DIR.mkdir(parents=True, exist_ok=True)
            data = {
                name: {
                    "value": entry.value,
                    "description": entry.description,
                    "created_at": entry.created_at,
                }
                for name, entry in self._secrets.items()
            }
            encrypted = _encrypt(json.dumps(data))
            self._disk_path().write_bytes(encrypted)
            os.chmod(self._disk_path(), 0o600)
        except Exception:
            logger.debug("secret_persist_failed", session_id=self._session_id, exc_info=True)

    def _load_from_disk(self) -> None:
        path = self._disk_path()
        if not path.exists():
            return
        try:
            raw = _decrypt(path.read_bytes())
            data = json.loads(raw)
            now = time.time()
            for name, info in data.items():
                created = info.get("created_at", now)
                if now - created > self._ttl:
                    continue
                self._secrets[name] = SecretEntry(
                    name=name,
                    description=info.get("description", ""),
                    created_at=created,
                    _value=info["value"],
                )
            if self._secrets:
                logger.info(
                    "secrets_restored",
                    session_id=self._session_id,
                    count=len(self._secrets),
                )
        except Exception:
            logger.debug("secret_restore_failed", session_id=self._session_id, exc_info=True)

    def store(self, name: str, value: str, description: str = "") -> None:
        self._secrets[name] = SecretEntry(
            name=name, description=description, _value=value
        )
        if name in self._pending:
            self._pending[name].set()
        logger.info("secret_stored", session_id=self._session_id, name=name)
        self._save_to_disk()

    def get(self, name: str) -> str | None:
        entry = self._secrets.get(name)
        if entry is None:
            return None
        if time.time() - entry.created_at > self._ttl:
            self._secrets.pop(name, None)
            logger.info("secret_expired", session_id=self._session_id, name=name)
            self._save_to_disk()
            return None
        return entry.value

    def list_names(self) -> list[dict[str, str]]:
        self._evict_expired()
        return [
            {"name": e.name, "description": e.description}
            for e in self._secrets.values()
        ]

    def get_all(self) -> dict[str, str]:
        self._evict_expired()
        return {name: e.value for name, e in self._secrets.items()}

    def delete(self, name: str) -> bool:
        removed = self._secrets.pop(name, None)
        if removed:
            self._save_to_disk()
        return removed is not None

    def clear(self) -> None:
        self._secrets.clear()
        with contextlib.suppress(OSError):
            self._disk_path().unlink(missing_ok=True)

    def create_pending(self, name: str) -> asyncio.Event:
        if name in self._pending:
            return self._pending[name]
        evt = asyncio.Event()
        self._pending[name] = evt
        return evt

    def cleanup_pending(self, name: str) -> None:
        self._pending.pop(name, None)

    def cancel_all_pending(self) -> None:
        for evt in self._pending.values():
            evt.set()
        self._pending.clear()

    def redact(self, text: str) -> str:
        self._evict_expired()
        for name, entry in self._secrets.items():
            val = entry.value
            if len(val) < _SECRET_MIN_LENGTH:
                continue
            if val in text:
                text = text.replace(val, REDACTION_PLACEHOLDER.format(name=name))
        return text

    def redact_dict(self, data: dict[str, Any]) -> dict[str, Any]:
        return _redact_recursive(data, self.redact)

    def _evict_expired(self) -> None:
        now = time.time()
        expired = [n for n, e in self._secrets.items() if now - e.created_at > self._ttl]
        if expired:
            for n in expired:
                self._secrets.pop(n, None)
            self._save_to_disk()

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
    if isinstance(obj, str):
        return redact_fn(obj)
    if isinstance(obj, dict):
        return {k: _redact_recursive(v, redact_fn) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_redact_recursive(i, redact_fn) for i in obj]
    return obj


def build_secret_pattern(vault: SessionVault) -> re.Pattern[str] | None:
    values = [re.escape(e.value) for e in vault._secrets.values() if len(e.value) >= _SECRET_MIN_LENGTH]
    if not values:
        return None
    return re.compile("|".join(values))
