"""Detect configuration drift by running playbooks in check mode and analyzing changes."""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.persistence.infrastructure_store import InfrastructureStore
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.executor import (
    _runner_envvars,
    get_runner_events,
    isolated_runner_dir,
    kill_stale_runner_procs,
    materialize_ssh_keys,
)

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


class DriftDetector(BaseTool):
    @property
    def name(self) -> str:
        return "detect_drift"

    @property
    def description(self) -> str:
        return (
            "Detect configuration drift by running a playbook in check mode with --diff "
            "and analyzing which tasks would produce changes. Each detected change is "
            "recorded as a drift record in the infrastructure store. Use this to verify "
            "that hosts still match their desired state."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "playbook": {
                    "type": "string",
                    "description": "Playbook filename (relative to project directory) that defines desired state",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "limit": {
                    "type": "string",
                    "description": "Limit drift check to specific hosts/groups",
                },
            },
            "required": ["workspace_path", "playbook", "inventory"],
        }

    @staticmethod
    def _materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
        return materialize_ssh_keys(keys_dir, merged_vars)

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        stripped = inventory.removeprefix("inventory/").removeprefix("inventory\\")
        candidates = [ws / "inventory" / stripped, ws / inventory, ws / "inventory" / inventory]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    async def execute(
        self,
        workspace_path: str = "",
        playbook: str = "",
        inventory: str = "",
        limit: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not playbook or not inventory:
            return ToolResult.fail("workspace_path, playbook, and inventory are required")

        ws = Path(workspace_path)
        if not (ws / playbook).exists():
            return ToolResult.fail(f"Playbook not found: {ws / playbook}")

        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        from ansible_forge.tools.python_resolver import resolve_or_install_python_async

        await resolve_or_install_python_async()

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())

        drift_items: list[dict[str, Any]] = []
        store = InfrastructureStore.get_instance()

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", extravars)
            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "project_dir": str(ws),
                "playbook": playbook,
                "inventory": str(inv_path),
                "cmdline": "--check --diff",
                "envvars": _runner_envvars(),
            }
            if limit:
                runner_kwargs["cmdline"] += f" --limit {limit}"
            if extravars:
                runner_kwargs["extravars"] = extravars

            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, functools.partial(ansible_runner.run, **runner_kwargs)
                    ),
                    timeout=300,
                )
            except TimeoutError:
                kill_stale_runner_procs(run_dir)
                return ToolResult.fail("Drift detection timed out after 5 minutes.")

            all_events = get_runner_events(result)

            for event in all_events:
                ev_type = event.get("event", "")
                if ev_type not in ("runner_on_changed", "runner_on_failed"):
                    continue

                ed = event.get("event_data", {})
                host = ed.get("host", "unknown")
                task = ed.get("task", "unknown")
                res = ed.get("res", {})

                diff_info = res.get("diff", {})
                before = ""
                after = ""
                if isinstance(diff_info, dict):
                    before = str(diff_info.get("before", ""))[:500]
                    after = str(diff_info.get("after", ""))[:500]
                elif isinstance(diff_info, list):
                    parts = [str(d.get("before", "")) for d in diff_info if isinstance(d, dict)]
                    before = "; ".join(parts)[:500]
                    parts = [str(d.get("after", "")) for d in diff_info if isinstance(d, dict)]
                    after = "; ".join(parts)[:500]

                field = task
                if res.get("invocation", {}).get("module_name"):
                    field = f"{res['invocation']['module_name']}: {task}"

                drift_id = store.record_drift(
                    host_id=host,
                    field=field,
                    expected_value=after or "desired state",
                    actual_value=before or "current state",
                )

                drift_items.append({
                    "drift_id": drift_id,
                    "host": host,
                    "task": task,
                    "type": "changed" if ev_type == "runner_on_changed" else "failed",
                    "before": before[:200],
                    "after": after[:200],
                    "msg": res.get("msg", ""),
                })

            skipped = sum(1 for e in all_events if e.get("event") == "runner_on_skipped")
            ok = sum(1 for e in all_events if e.get("event") == "runner_on_ok")

        if not drift_items:
            return ToolResult.ok(
                output=f"No drift detected. {ok} task(s) in desired state, {skipped} skipped.",
                drift_count=0,
                ok_count=ok,
                skipped_count=skipped,
            )

        return ToolResult.ok(
            output=(
                f"Drift detected: {len(drift_items)} item(s) would change. "
                f"{ok} in desired state, {skipped} skipped. "
                f"Drift records saved to infrastructure store."
            ),
            drift_items=drift_items,
            drift_count=len(drift_items),
            ok_count=ok,
            skipped_count=skipped,
        )
