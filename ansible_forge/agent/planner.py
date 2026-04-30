"""Task decomposition and planning for the agent orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from ansible_forge.agent.prompts.templates import PLAYBOOK_CONTEXT
from ansible_forge.logging import get_logger
from ansible_forge.workspace.manager import Workspace
from ansible_forge.workspace.project_layout import list_playbooks

logger = get_logger(__name__)


def build_context(workspace: Workspace) -> str:
    """Build a context string describing the current workspace state."""
    inv_files = _list_dir(workspace.inventory_dir)
    playbooks = list_playbooks(workspace.path)
    roles = _list_roles(workspace.project_dir / "roles")

    ctx = PLAYBOOK_CONTEXT.format(
        workspace_path=str(workspace.path),
        inventory_files=", ".join(inv_files) or "(none)",
        playbook_files=", ".join(playbooks) or "(none)",
        role_names=", ".join(roles) or "(none)",
    )

    facts_summary = _load_cached_facts(workspace.path)
    if facts_summary:
        ctx += f"\n{facts_summary}"
    return ctx


def _load_cached_facts(workspace_root: Path) -> str:
    """Read host_facts.json and return a compact one-line-per-host summary."""
    facts_path = workspace_root / "artifacts" / "host_facts.json"
    if not facts_path.exists():
        return ""
    try:
        host_facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("cached_facts_unreadable", path=str(facts_path))
        return ""

    lines = ["Known host facts:"]
    for host, f in host_facts.items():
        distro = f.get("distribution", "?")
        version = f.get("distribution_version", "")
        arch = f.get("architecture", "")
        pkg = f.get("pkg_mgr", "?")
        svc = f.get("service_mgr", "?")
        se = f.get("selinux", "")
        py = f.get("python_interpreter", "") or f.get("python_version", "")
        mem = f.get("memory_mb", 0)
        ram = f"{mem}MB" if mem else "?"
        lines.append(
            f"  {host}: {distro} {version}, {arch}, {pkg}, {svc}, "
            f"SELinux={se or 'n/a'}, Python={py}, {ram} RAM"
        )
    return "\n".join(lines)


def _list_dir(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [f.name for f in path.iterdir() if f.is_file()]


def _list_roles(roles_dir: Path) -> list[str]:
    if not roles_dir.exists():
        return []
    return [d.name for d in roles_dir.iterdir() if d.is_dir()]
