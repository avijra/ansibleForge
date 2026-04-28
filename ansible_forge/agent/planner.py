"""Task decomposition and planning for the agent orchestrator."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.agent.prompts.templates import PLAYBOOK_CONTEXT
from ansible_forge.workspace.manager import Workspace
from ansible_forge.workspace.project_layout import list_playbooks


def build_context(workspace: Workspace) -> str:
    """Build a context string describing the current workspace state."""
    inv_files = _list_dir(workspace.inventory_dir)
    playbooks = list_playbooks(workspace.path)
    roles = _list_roles(workspace.project_dir / "roles")

    return PLAYBOOK_CONTEXT.format(
        workspace_path=str(workspace.path),
        inventory_files=", ".join(inv_files) or "(none)",
        playbook_files=", ".join(playbooks) or "(none)",
        role_names=", ".join(roles) or "(none)",
    )


def _list_dir(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [f.name for f in path.iterdir() if f.is_file()]


def _list_roles(roles_dir: Path) -> list[str]:
    if not roles_dir.exists():
        return []
    return [d.name for d in roles_dir.iterdir() if d.is_dir()]
