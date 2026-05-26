from __future__ import annotations

import fcntl
import threading
from pathlib import Path

_MAX_CHARS = 3000
_MEMORY_FILENAME = "MEMORY.md"

_workspace_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _get_workspace_lock(workspace_id: str) -> threading.Lock:
    with _locks_guard:
        if workspace_id not in _workspace_locks:
            _workspace_locks[workspace_id] = threading.Lock()
        return _workspace_locks[workspace_id]


class WorkspaceMemory:
    def __init__(self, workspace_id: str, base_dir: Path | None = None):
        self._workspace_id = workspace_id
        root = base_dir or (Path.home() / ".ansibleforge" / "workspaces")
        self._dir = root / workspace_id
        self._path = self._dir / _MEMORY_FILENAME
        self._lock = _get_workspace_lock(workspace_id)

    @property
    def path(self) -> Path:
        return self._path

    def read(self) -> str:
        if not self._path.exists():
            return ""
        return self._path.read_text(encoding="utf-8")

    def _write(self, content: str) -> str:
        if len(content) > _MAX_CHARS:
            return (
                f"Memory exceeds {_MAX_CHARS} character limit "
                f"({len(content)} chars). Remove entries before adding more."
            )
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path.write_text(content, encoding="utf-8")
        return ""

    def _locked_read_modify_write(self, fn):
        """Acquire both in-process lock and file-level lock for safe RMW."""
        with self._lock:
            self._dir.mkdir(parents=True, exist_ok=True)
            lock_file = self._dir / ".memory.lock"
            with open(lock_file, "w") as lf:
                fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
                try:
                    return fn()
                finally:
                    fcntl.flock(lf.fileno(), fcntl.LOCK_UN)

    def add(self, entry: str) -> str:
        new_line = entry.strip()
        if not new_line:
            return "Empty entry — nothing added."

        def _do():
            current = self.read()
            separator = "\n" if current and not current.endswith("\n") else ""
            candidate = f"{current}{separator}{new_line}\n"
            err = self._write(candidate)
            return err or f"Added to workspace memory ({len(candidate)}/{_MAX_CHARS} chars)."

        return self._locked_read_modify_write(_do)

    def replace(self, old_text: str, new_text: str) -> str:
        def _do():
            current = self.read()
            if old_text not in current:
                return f"Text not found in memory: {old_text[:80]}"
            updated = current.replace(old_text, new_text, 1)
            err = self._write(updated)
            return err or "Replaced in workspace memory."

        return self._locked_read_modify_write(_do)

    def remove(self, pattern: str) -> str:
        def _do():
            current = self.read()
            lines = current.splitlines(keepends=True)
            kept = [ln for ln in lines if pattern not in ln]
            if len(kept) == len(lines):
                return f"No lines matched pattern: {pattern[:80]}"
            removed = len(lines) - len(kept)
            updated = "".join(kept)
            err = self._write(updated)
            return err or f"Removed {removed} line(s) from workspace memory."

        return self._locked_read_modify_write(_do)

    def clear(self) -> str:
        with self._lock:
            if self._path.exists():
                self._path.write_text("", encoding="utf-8")
        return "Workspace memory cleared."

    def inject_context(self) -> str:
        content = self.read().strip()
        if not content:
            return ""
        return (
            "---\n"
            "Workspace memory (MEMORY.md — curated facts, may be stale):\n"
            "WARNING: This is a NEW session. Hostnames, cluster names, credentials, "
            "and environment details below may be outdated. Do NOT assume they are "
            "current — verify with the user before using any specific values.\n"
            f"{content}\n"
        )
