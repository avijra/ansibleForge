"""Manage session-isolated workspaces for ansible-runner execution."""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

WORKSPACE_SUBDIRS = ("project", "inventory", "env", "artifacts", "knowledge")


class WorkspaceManager:
    """Creates and manages temporary workspaces with ansible-runner layout."""

    def __init__(self, base_dir: Path | None = None) -> None:
        settings = get_settings()
        self._base = base_dir or settings.workspace_dir
        self._ttl = settings.workspace_ttl_seconds
        self._base.mkdir(parents=True, exist_ok=True)

    def create(self, session_id: str | None = None) -> Workspace:
        sid = session_id or uuid.uuid4().hex[:12]
        ws_path = self._base / sid
        ws_path.mkdir(parents=True, exist_ok=True)

        for subdir in WORKSPACE_SUBDIRS:
            (ws_path / subdir).mkdir(exist_ok=True)

        logger.info("workspace_created", session_id=sid, path=str(ws_path))
        return Workspace(session_id=sid, path=ws_path)

    def get(self, session_id: str) -> Workspace | None:
        ws_path = self._base / session_id
        if ws_path.is_dir():
            return Workspace(session_id=session_id, path=ws_path)
        return None

    def destroy(self, session_id: str) -> bool:
        ws_path = self._base / session_id
        if ws_path.is_dir():
            shutil.rmtree(ws_path, ignore_errors=True)
            logger.info("workspace_destroyed", session_id=session_id)
            return True
        return False

    def cleanup_expired(self) -> int:
        """Remove workspaces older than TTL. Returns count removed."""
        removed = 0
        cutoff = time.time() - self._ttl

        if not self._base.exists():
            return 0

        for entry in self._base.iterdir():
            if entry.is_dir() and entry.stat().st_mtime < cutoff:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1
                logger.debug("workspace_expired", path=str(entry))

        if removed:
            logger.info("workspaces_cleaned", count=removed)
        return removed


class Workspace:
    """Represents a single session workspace."""

    def __init__(self, session_id: str, path: Path) -> None:
        self.session_id = session_id
        self.path = path

    @property
    def project_dir(self) -> Path:
        return self.path / "project"

    @property
    def inventory_dir(self) -> Path:
        return self.path / "inventory"

    @property
    def env_dir(self) -> Path:
        return self.path / "env"

    @property
    def artifacts_dir(self) -> Path:
        return self.path / "artifacts"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "project_dir": str(self.project_dir),
            "inventory_dir": str(self.inventory_dir),
        }
