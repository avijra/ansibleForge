"""Build a knowledge-graph context string for injection into LLM prompts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ansible_forge.knowledge.graph import KnowledgeGraph
from ansible_forge.logging import get_logger

if TYPE_CHECKING:
    from ansible_forge.workspace.manager import Workspace

logger = get_logger(__name__)

_HOST_PATTERN = re.compile(
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b"
    r"|(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}"
)
_MODULE_PATTERN = re.compile(
    r"\b[a-z_]+\.[a-z_]+\.[a-z_]+\b"
)


def _extract_hosts_from_workspace(workspace: Workspace | None) -> set[str]:
    """Extract hostnames from inventory files and cached facts."""
    hosts: set[str] = set()
    if workspace is None:
        return hosts

    facts_file = workspace.artifacts_dir / "host_facts.json"
    if facts_file.is_file():
        try:
            data = json.loads(facts_file.read_text(encoding="utf-8"))
            hosts.update(data.keys())
        except (json.JSONDecodeError, OSError):
            pass

    inv_dir = workspace.inventory_dir
    if inv_dir.is_dir():
        for inv_file in inv_dir.iterdir():
            if not inv_file.is_file():
                continue
            try:
                content = inv_file.read_text(encoding="utf-8")
                hosts.update(_HOST_PATTERN.findall(content))
            except OSError:
                pass

    hosts.discard("0.0.0.0")
    return hosts


def _extract_modules_from_workspace(workspace: Workspace | None) -> set[str]:
    """Extract module FQCNs from playbook files in the project directory."""
    modules: set[str] = set()
    if workspace is None:
        return modules

    project_dir = workspace.project_dir
    if not project_dir.is_dir():
        return modules

    for yml_file in project_dir.rglob("*.yml"):
        try:
            content = yml_file.read_text(encoding="utf-8")
            modules.update(_MODULE_PATTERN.findall(content))
        except OSError:
            pass

    return modules


def _extract_mentions_from_messages(messages: list[Any]) -> tuple[set[str], set[str]]:
    """Fallback: pull hosts and modules from recent chat messages."""
    hosts: set[str] = set()
    modules: set[str] = set()
    tail = messages[-10:] if len(messages) > 10 else messages
    for msg in tail:
        text = ""
        if isinstance(msg, dict):
            text = msg.get("content") or ""
        elif isinstance(msg, str):
            text = msg
        else:
            continue
        if isinstance(text, list):
            text = " ".join(str(p) for p in text)
        if not isinstance(text, str):
            continue
        hosts.update(_HOST_PATTERN.findall(text))
        modules.update(_MODULE_PATTERN.findall(text))
    hosts.discard("0.0.0.0")
    return hosts, modules


def _format_errors(rows: list[list[Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        template, os_fam, resolution, success = row
        entry = f"  - [{os_fam or '?'}] {template}"
        if resolution:
            status = "fixed" if success else "attempted"
            entry += f" -> {status}: {resolution}"
        lines.append(entry)
    return lines


def _format_host_history(rows: list[list[Any]]) -> list[str]:
    lines: list[str] = []
    for row in rows:
        task_name, module_fqcn, outcome, _ts = row
        mod = f" ({module_fqcn})" if module_fqcn else ""
        lines.append(f"  - {task_name}{mod} -> {outcome}")
    return lines


def build_knowledge_context(
    global_graph: KnowledgeGraph | None,
    project_graph: KnowledgeGraph | None,
    messages: list[Any],
    workspace: Workspace | None = None,
) -> str:
    """Query both graphs for context relevant to the current conversation.

    Uses workspace inventory/facts and playbook files as the primary source
    for host and module mentions (deterministic), with chat message regex
    as a fallback.
    """
    if global_graph is None and project_graph is None:
        return ""

    hosts = _extract_hosts_from_workspace(workspace)
    modules = _extract_modules_from_workspace(workspace)

    msg_hosts, msg_modules = _extract_mentions_from_messages(messages)
    hosts.update(msg_hosts)
    modules.update(msg_modules)

    sections: list[str] = []

    if global_graph is not None:
        for mod in sorted(modules):
            try:
                rows = global_graph.query_errors_for_module(mod, limit=5)
            except Exception:
                continue
            if rows:
                lines = _format_errors(rows)
                sections.append(f"Known issues with `{mod}`:\n" + "\n".join(lines))

        try:
            recent = global_graph.query_recent_errors(limit=5)
        except Exception:
            recent = []
        if recent and not modules:
            lines = []
            for row in recent:
                tmpl, mod, os_f, resolution, success = row
                entry = f"  - [{mod or '?'} on {os_f or '?'}] {tmpl}"
                if resolution:
                    tag = "fixed" if success else "attempted"
                    entry += f" -> {tag}: {resolution}"
                lines.append(entry)
            sections.append("Recent error patterns:\n" + "\n".join(lines))

    if project_graph is not None:
        for host in sorted(hosts):
            try:
                info = project_graph.query_host_info(host)
            except Exception:
                info = []
            try:
                history = project_graph.query_host_history(host, limit=8)
            except Exception:
                history = []

            if info or history:
                parts: list[str] = []
                if info:
                    os_f, dist, arch = info[0]
                    parts.append(f"  OS: {dist or os_f or '?'}, arch: {arch or '?'}")
                if history:
                    parts.extend(_format_host_history(history))
                sections.append(f"Host `{host}`:\n" + "\n".join(parts))

    if not sections:
        return ""

    return "---\nKnowledge graph context:\n" + "\n\n".join(sections) + "\n"
