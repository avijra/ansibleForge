"""Manage user-owned project workspaces with ansible-runner integration."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Any

from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

RUNNER_SUBDIR = ".tuyere"
RUNNER_INTERNALS = ("env", "artifacts", "ssh_keys")


class WorkspaceManager:
    """Creates and manages user-owned project workspaces.

    Each workspace is a user-visible directory where playbooks, inventory,
    roles, and templates are written directly.  ansible-runner's ephemeral
    state lives in a ``.tuyere/`` subdirectory that is auto-gitignored.
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        settings = get_settings()
        self._base = base_dir or settings.default_project_dir
        self._base.mkdir(parents=True, exist_ok=True)

    def create(
        self,
        session_id: str | None = None,
        project_path: Path | str | None = None,
    ) -> Workspace:
        sid = session_id or uuid.uuid4().hex[:12]

        ws_path = Path(project_path).expanduser().resolve() if project_path else self._base / sid

        ws_path.mkdir(parents=True, exist_ok=True)
        (ws_path / "inventory").mkdir(exist_ok=True)

        runner_dir = ws_path / RUNNER_SUBDIR
        runner_dir.mkdir(exist_ok=True)
        for subdir in RUNNER_INTERNALS:
            (runner_dir / subdir).mkdir(exist_ok=True)

        gitignore = runner_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("*\n")

        logger.info("workspace_created", session_id=sid, path=str(ws_path))
        return Workspace(session_id=sid, path=ws_path)

    def get(self, session_id: str) -> Workspace | None:
        ws_path = self._base / session_id
        if ws_path.is_dir():
            return Workspace(session_id=session_id, path=ws_path)
        return None

    def get_by_path(self, project_path: str | Path) -> Workspace | None:
        p = Path(project_path).expanduser().resolve()
        if p.is_dir():
            return Workspace(session_id=p.name, path=p)
        return None

    def destroy(self, session_id: str) -> bool:
        ws_path = self._base / session_id
        runner = ws_path / RUNNER_SUBDIR
        if runner.is_dir():
            shutil.rmtree(runner, ignore_errors=True)
            logger.info("workspace_runner_cleaned", session_id=session_id)
            return True
        return False


class Workspace:
    """Represents a user-owned project workspace.

    The project directory is the user's folder itself — playbooks, inventory,
    roles, and templates live at the root.  ansible-runner internals (env,
    artifacts, ssh_keys) are tucked into ``.tuyere/``.
    """

    def __init__(self, session_id: str, path: Path) -> None:
        self.session_id = session_id
        self.path = path

    @property
    def project_dir(self) -> Path:
        return self.path

    @property
    def inventory_dir(self) -> Path:
        return self.path / "inventory"

    _CORE_DIRS = ("scripts",)

    _PROFILE_DIRS: dict[str, tuple[str, ...]] = {
        "ansible": ("inventory", "playbooks", "roles", "group_vars", "templates"),
        "terraform": ("terraform",),
        "gitops": ("k8s", "helm"),
        "devops": ("docker", "pipelines"),
    }

    def scaffold_layout(self, profiles: set[str] | None = None) -> list[str]:
        dirs: list[str] = list(self._CORE_DIRS)
        for profile in (profiles or set()):
            dirs.extend(self._PROFILE_DIRS.get(profile, ()))
        created: list[str] = []
        for d in dirs:
            target = self.path / d
            if not target.exists():
                target.mkdir(parents=True, exist_ok=True)
                created.append(d)
        return created

    @property
    def runner_dir(self) -> Path:
        return self.path / RUNNER_SUBDIR

    @property
    def env_dir(self) -> Path:
        return self.runner_dir / "env"

    @property
    def artifacts_dir(self) -> Path:
        return self.runner_dir / "artifacts"

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "path": str(self.path),
            "project_dir": str(self.project_dir),
            "inventory_dir": str(self.inventory_dir),
        }
