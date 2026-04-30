"""Extract entities and relationships from tool results into the knowledge graph."""

from __future__ import annotations

import contextlib
import hashlib
import re
import time
import uuid
from typing import Any

from ansible_forge.knowledge.graph import KnowledgeGraph
from ansible_forge.logging import get_logger
from ansible_forge.tools.base import ToolResult, ToolStatus

logger = get_logger(__name__)

_HOST_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_SECRET_KEYS = frozenset({
    "ansible_ssh_pass", "ansible_become_pass", "ansible_become_password",
    "password", "secret", "token", "api_key",
})


def _sanitise_error(msg: str) -> str:
    """Strip host-specific details from error messages for deduplication."""
    sanitised = _HOST_RE.sub("<HOST>", msg)
    for pattern in (r"/tmp/\S+", r"/home/\S+"):
        sanitised = re.sub(pattern, "<PATH>", sanitised)
    return sanitised.strip()[:500]


def _error_hash(sanitised: str, module: str) -> str:
    raw = f"{module}::{sanitised}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _task_id(task_name: str, host: str) -> str:
    raw = f"{task_name}::{host}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _has_secret_keys(d: dict[str, Any]) -> bool:
    return bool(_SECRET_KEYS & set(d))


def ingest_tool_result(
    tool_name: str,
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    """Route a tool result to the appropriate extractor."""
    try:
        _EXTRACTORS.get(tool_name, _noop)(
            result, session_id, global_graph, project_graph
        )
    except Exception:
        logger.warning("knowledge_extract_failed", tool=tool_name, exc_info=True)


def _noop(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    pass


def _extract_executor(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    data = result.data
    summary = data.get("summary", {})
    events: list[dict[str, Any]] = data.get("events", [])
    mode = data.get("mode", "apply")
    now = int(time.time())
    execution_id = uuid.uuid4().hex[:12]

    playbook_name = data.get("playbook", "unknown")
    exec_kwargs = {
        "execution_id": execution_id,
        "session_id": session_id,
        "timestamp": now,
        "mode": mode,
        "status": summary.get("status", "unknown"),
        "rc": summary.get("rc", -1),
    }

    for graph in (project_graph, global_graph):
        graph.merge_playbook(playbook_name)
        graph.create_execution(**exec_kwargs)
        with contextlib.suppress(Exception):
            graph.link_execution_runs(execution_id, playbook_name)

    seen_hosts: set[str] = set()
    prev_errors: dict[str, str] = {}

    for event in events:
        host = event.get("host", "")
        task_name = event.get("task", "")
        event_type = event.get("event", "")
        task_result = event.get("result", {})

        if not host or not task_name:
            continue

        tid = _task_id(task_name, host)
        module_fqcn = task_result.get("module_fqcn", "") or ""

        for graph in (project_graph, global_graph):
            graph.merge_host(hostname=host, last_seen=now)
            graph.merge_task(task_id=tid, name=task_name, module_fqcn=module_fqcn)

        if host not in seen_hosts:
            seen_hosts.add(host)
            for graph in (project_graph, global_graph):
                with contextlib.suppress(Exception):
                    graph.link_execution_targets(execution_id, host)

        outcome = event_type.replace("runner_on_", "")
        for graph in (project_graph, global_graph):
            with contextlib.suppress(Exception):
                graph.link_ran_task(host, tid, outcome, now)

        if module_fqcn:
            global_graph.merge_module(module_fqcn)
            for graph in (project_graph, global_graph):
                with contextlib.suppress(Exception):
                    graph.link_uses_module(tid, module_fqcn)

        if event_type == "runner_on_failed":
            error_msg = str(task_result.get("msg", ""))
            if error_msg:
                sanitised = _sanitise_error(error_msg)
                mhash = _error_hash(sanitised, module_fqcn)
                global_graph.merge_error_pattern(
                    message_hash=mhash,
                    message_template=sanitised,
                    module=module_fqcn,
                    first_seen=now,
                )
                with contextlib.suppress(Exception):
                    global_graph.link_error_occurred_on(mhash, host)
                with contextlib.suppress(Exception):
                    global_graph.link_error_during_task(mhash, tid)
                prev_errors[tid] = mhash

        if event_type == "runner_on_ok" and tid in prev_errors:
            mhash = prev_errors.pop(tid)
            rid = uuid.uuid4().hex[:12]
            global_graph.create_resolution(
                resolution_id=rid,
                description=f"Task '{task_name}' succeeded after prior failure",
                action_taken=f"module={module_fqcn}",
                success=True,
                created_at=now,
            )
            with contextlib.suppress(Exception):
                global_graph.link_resolution_resolves(rid, mhash)


def _extract_facts(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    if result.status != ToolStatus.SUCCESS:
        return
    host_facts: dict[str, dict[str, Any]] = result.data.get("host_facts", {})
    now = int(time.time())

    for hostname, facts in host_facts.items():
        project_graph.merge_host(
            hostname=hostname,
            os_family=facts.get("os_family", ""),
            distribution=facts.get("distribution", ""),
            distribution_version=facts.get("distribution_version", ""),
            architecture=facts.get("architecture", ""),
            kernel=facts.get("kernel", ""),
            last_seen=now,
        )
        global_graph.merge_host(
            hostname=hostname,
            os_family=facts.get("os_family", ""),
            distribution=facts.get("distribution", ""),
            last_seen=now,
        )


def _extract_playbook_gen(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    if result.status != ToolStatus.SUCCESS:
        return
    path = result.data.get("path", "")
    if path:
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        project_graph.merge_playbook(name, path)


def _extract_role_scaffold(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    if result.status != ToolStatus.SUCCESS:
        return
    path = result.data.get("path", "")
    if path:
        name = path.rsplit("/", 1)[-1] if "/" in path else path
        project_graph.merge_role(name, path)


def _extract_inventory(
    result: ToolResult,
    session_id: str,
    global_graph: KnowledgeGraph,
    project_graph: KnowledgeGraph,
) -> None:
    if result.status != ToolStatus.SUCCESS:
        return
    now = int(time.time())
    hosts: list[str] = result.data.get("hosts", [])
    for hostname in hosts:
        if hostname and not _has_secret_keys(result.data):
            project_graph.merge_host(hostname=hostname, last_seen=now)


_EXTRACTORS: dict[str, Any] = {
    "execute_playbook": _extract_executor,
    "collect_facts": _extract_facts,
    "generate_playbook": _extract_playbook_gen,
    "scaffold_role": _extract_role_scaffold,
    "manage_inventory": _extract_inventory,
}
