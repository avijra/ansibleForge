"""Infrastructure tracking — records host state and run history after tool execution."""

from __future__ import annotations

import asyncio
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import ToolResult, ToolStatus

logger = get_logger(__name__)


async def update_infrastructure(
    tool_name: str,
    result: ToolResult,
    session_id: str,
    pending_run_id: int | None = None,
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None, _update_infrastructure_sync,
        tool_name, result, session_id, pending_run_id,
    )


def _update_infrastructure_sync(
    tool_name: str,
    result: ToolResult,
    session_id: str,
    pending_run_id: int | None = None,
) -> None:
    try:
        from ansible_forge.persistence.infrastructure_store import InfrastructureStore
        store = InfrastructureStore.get_instance()

        if tool_name == "collect_facts" and result.status == ToolStatus.SUCCESS:
            host_facts = result.data.get("host_facts", {})
            for hostname, facts in host_facts.items():
                host_id = store.upsert_host(
                    hostname=hostname,
                    ip_address=facts.get("default_ipv4", ""),
                    status="reachable",
                )
                drifts = store.detect_drift(host_id, facts)
                if drifts:
                    logger.info(
                        "drift_detected",
                        host=hostname,
                        drifts=drifts,
                        session_id=session_id,
                    )
                store.save_facts(host_id, facts)

        elif tool_name == "test_connectivity" and result.status == ToolStatus.SUCCESS:
            events = result.data.get("events", [])
            for event in events:
                host = event.get("host", "")
                if host:
                    status = "reachable" if event.get("event") == "runner_on_ok" else "unreachable"
                    store.upsert_host(hostname=host, status=status)

        elif tool_name == "execute_playbook":
            data = result.data
            playbook = data.get("playbook", "unknown")
            mode = data.get("mode", "unknown")
            events = data.get("events", [])
            hosts = list({e.get("host", "") for e in events if e.get("host")})
            status = "success" if result.status == ToolStatus.SUCCESS else "failed"

            if pending_run_id:
                store.update_run(
                    run_id=pending_run_id,
                    status=status,
                    hosts=hosts,
                    event_count=len(events),
                    summary=data.get("summary"),
                )
            else:
                store.record_run(
                    session_id=session_id,
                    playbook=playbook,
                    mode=mode,
                    hosts=hosts,
                    status=status,
                    event_count=len(events),
                    summary=data.get("summary"),
                )

            for host in hosts:
                if host:
                    host_status = "configured" if (result.status == ToolStatus.SUCCESS and mode == "apply") else "reachable"
                    store.upsert_host(hostname=host, status=host_status)

        elif tool_name == "run_adhoc":
            data = result.data
            host_results = data.get("host_results", {})
            module = data.get("module", "shell")
            module_args = data.get("module_args", "")
            hosts = list(host_results.keys())
            status = "success" if result.status == ToolStatus.SUCCESS else "failed"
            label = module_args[:80] if module_args else module

            if pending_run_id:
                store.update_run(
                    run_id=pending_run_id,
                    status=status,
                    hosts=hosts,
                    event_count=1,
                    summary={"module": module},
                )
            else:
                store.record_run(
                    session_id=session_id,
                    playbook=f"adhoc: {label}",
                    mode="adhoc",
                    hosts=hosts,
                    status=status,
                    event_count=1,
                    summary={"module": module},
                )

            for host in hosts:
                if host:
                    store.upsert_host(hostname=host, status="reachable")

        elif tool_name == "terraform_exec":
            data = result.data
            action = data.get("action", "unknown")
            status = "success" if result.status == ToolStatus.SUCCESS else "failed"

            if pending_run_id:
                store.update_run(
                    run_id=pending_run_id,
                    status=status,
                    hosts=["localhost"],
                    event_count=1,
                    summary=data.get("output_summary", {}),
                )
            else:
                store.record_run(
                    session_id=session_id,
                    playbook=f"terraform {action}",
                    mode=action,
                    hosts=["localhost"],
                    status=status,
                    event_count=1,
                    summary=data.get("output_summary", {}),
                )

        elif tool_name == "verify_state":
            results = result.data.get("results", [])
            for check in results:
                host = check.get("host", "")
                if host and check.get("status") == "PASS":
                    store.update_host_status(
                        host.replace(".", "_").replace(":", "_"),
                        "verified",
                    )

    except Exception:
        logger.debug("infrastructure_update_failed", tool=tool_name, exc_info=True)
