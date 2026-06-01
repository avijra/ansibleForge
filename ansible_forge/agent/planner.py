"""Task decomposition and planning for the agent orchestrator."""

from __future__ import annotations

import json
from pathlib import Path

from ansible_forge.agent.prompts.templates import PLAYBOOK_CONTEXT
from ansible_forge.logging import get_logger
from ansible_forge.workspace.manager import Workspace
from ansible_forge.workspace.project_layout import list_playbooks

logger = get_logger(__name__)

_MAX_FILENAMES = 50
_MAX_CACHED_HOSTS = 30
_MAX_CONTEXT_CHARS = 6000


def _cap_list(items: list[str], limit: int) -> str:
    if not items:
        return "(none)"
    if len(items) <= limit:
        return ", ".join(items)
    return ", ".join(items[:limit]) + f" [{len(items) - limit} more]"


def build_context(workspace: Workspace) -> str:
    """Build a context string describing the current workspace state and known infrastructure."""
    inv_files = _list_dir(workspace.inventory_dir)
    playbooks = list_playbooks(workspace.path)
    roles = _list_roles(workspace.project_dir / "roles")
    tf_files = _list_dir(workspace.project_dir / "terraform")
    extra = _list_extra_files(workspace.project_dir)

    ctx = PLAYBOOK_CONTEXT.format(
        workspace_path=str(workspace.path),
        inventory_files=_cap_list(inv_files, _MAX_FILENAMES),
        playbook_files=_cap_list(playbooks, _MAX_FILENAMES),
        role_names=_cap_list(roles, _MAX_FILENAMES),
        terraform_files=_cap_list(tf_files, _MAX_FILENAMES),
        extra_files=extra,
    )

    facts_summary = _load_cached_facts(workspace.artifacts_dir)
    if facts_summary:
        ctx += f"\n{facts_summary}"

    infra_ctx = _load_infrastructure_context()
    if infra_ctx:
        ctx += f"\n{infra_ctx}"

    knowledge_ctx = _load_knowledge_context(workspace)
    if knowledge_ctx:
        ctx += f"\n{knowledge_ctx}"

    if len(ctx) > _MAX_CONTEXT_CHARS:
        ctx = ctx[:_MAX_CONTEXT_CHARS] + "\n[workspace context truncated]"

    return ctx


def _load_knowledge_context(workspace: Workspace) -> str:
    try:
        from ansible_forge.knowledge.packs import PackRegistry
        registry = PackRegistry(workspace.path)
        if not registry.pack_names:
            return ""
        return f"Available knowledge packs: {', '.join(registry.pack_names)} ({registry.total_pages} total pages)"
    except Exception:
        logger.debug("knowledge_context_unavailable", exc_info=True)
        return ""


def _load_infrastructure_context() -> str:
    try:
        from ansible_forge.persistence.infrastructure_store import InfrastructureStore
        store = InfrastructureStore.get_instance()
        return store.build_infrastructure_context()
    except Exception:
        logger.debug("infrastructure_context_unavailable", exc_info=True)
        return ""


def _load_cached_facts(artifacts_dir: Path) -> str:
    """Read host_facts.json and return a compact one-line-per-host summary."""
    facts_path = artifacts_dir / "host_facts.json"
    if not facts_path.exists():
        return ""
    try:
        host_facts = json.loads(facts_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("cached_facts_unreadable", path=str(facts_path))
        return ""

    if not isinstance(host_facts, dict):
        return ""

    items = list(host_facts.items())
    lines = ["Known host facts:"]
    for host, f in items[:_MAX_CACHED_HOSTS]:
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
    remaining = len(items) - _MAX_CACHED_HOSTS
    if remaining > 0:
        lines.append(f"  [{remaining} more hosts — use collect_facts to inspect]")
    return "\n".join(lines)


def _list_dir(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [f.name for f in path.iterdir() if f.is_file()]


def _list_roles(roles_dir: Path) -> list[str]:
    if not roles_dir.exists():
        return []
    return [d.name for d in roles_dir.iterdir() if d.is_dir()]


_SKIP_DIRS = frozenset({
    ".tuyere", ".git", "__pycache__", "node_modules",
    "inventory", "playbooks", "roles", "terraform",
})


def _list_extra_files(project_dir: Path) -> str:
    """List top-level files and notable subdirectories not covered by other sections."""
    if not project_dir.exists():
        return ""
    parts: list[str] = []
    for entry in sorted(project_dir.iterdir()):
        if entry.name.startswith(".") and entry.name != ".env" and entry.name not in (".github",):
            continue
        if entry.is_file():
            parts.append(f"  {entry.name}")
        elif entry.is_dir() and entry.name not in _SKIP_DIRS:
            children = sorted(p.name for p in entry.iterdir() if not p.name.startswith("."))[:10]
            if children:
                parts.append(f"  {entry.name}/: {', '.join(children)}")
    if not parts:
        return ""
    return "Other files:\n" + "\n".join(parts[:20])
