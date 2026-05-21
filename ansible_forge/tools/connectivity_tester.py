"""Quick connectivity test via ansible.builtin.ping — saves two tool calls vs generate+execute."""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.executor import (
    _resolve_python_interpreter,
    isolated_runner_dir,
    materialize_ssh_keys,
)
from ansible_forge.tools.secret_check import find_missing_secrets

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


def _connectivity_envvars() -> dict[str, str]:
    return {
        "ANSIBLE_PYTHON_INTERPRETER": _resolve_python_interpreter(),
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
    }


class ConnectivityTester(BaseTool):
    @property
    def name(self) -> str:
        return "test_connectivity"

    @property
    def description(self) -> str:
        return (
            "Test SSH connectivity to target hosts by running ansible.builtin.ping. "
            "Returns pass/fail per host with diagnostic output. Use this BEFORE "
            "generating playbooks to confirm the host is reachable."
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
                "host_pattern": {
                    "type": "string",
                    "description": "Host or group pattern to target (default: 'all')",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
            },
            "required": ["workspace_path", "inventory"],
        }

    @staticmethod
    def _materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
        return materialize_ssh_keys(keys_dir, merged_vars)

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        stripped = inventory.removeprefix("inventory/").removeprefix("inventory\\")
        candidates = [
            ws / "inventory" / stripped,
            ws / inventory,
            ws / "inventory" / inventory,
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    async def execute(
        self,
        workspace_path: str = "",
        host_pattern: str = "all",
        inventory: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not inventory:
            return ToolResult.fail("workspace_path and inventory are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())
        (ws / ".tuyere").mkdir(parents=True, exist_ok=True)

        missing = find_missing_secrets(inv_path, extravars)
        if missing:
            return ToolResult.fail(
                f"Inventory references secrets that are not in the vault: {', '.join(missing)}. "
                f"Use request_secret to collect them from the user before retrying."
            )

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", extravars)

            envvars = _connectivity_envvars()
            for key, value in extravars.items():
                if key.isupper() or key.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                    envvars[key] = str(value)
            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "module": "ansible.builtin.ping",
                "host_pattern": host_pattern,
                "inventory": str(inv_path),
                "envvars": envvars,
            }
            if extravars:
                runner_kwargs["extravars"] = extravars

            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, functools.partial(ansible_runner.run, **runner_kwargs)
                    ),
                    timeout=60,
                )
            except TimeoutError:
                return ToolResult.fail(
                    "Connection test timed out after 60 seconds. "
                    "Hosts may be behind a firewall or SSH is not configured."
                )

            passed: list[str] = []
            failed: list[dict[str, str]] = []
            for event in result.events:
                event_type = event.get("event", "")
                host = event.get("event_data", {}).get("host", "")
                if not host:
                    continue
                if event_type in ("runner_on_ok", "runner_on_changed"):
                    passed.append(host)
                elif event_type in ("runner_on_failed", "runner_on_unreachable"):
                    msg = event.get("event_data", {}).get("res", {}).get("msg", "")
                    stderr = event.get("event_data", {}).get("res", {}).get("stderr", "")
                    failed.append({
                        "host": host,
                        "error": msg or stderr or "host unreachable",
                    })

        if failed and not passed:
            diagnostics = "; ".join(
                f"{f['host']}: {f['error']}" for f in failed
            )
            return ToolResult.fail(
                f"All hosts unreachable. {diagnostics}",
                passed=passed,
                failed=failed,
            )

        summary_parts = []
        if passed:
            summary_parts.append(f"{len(passed)} host(s) reachable: {', '.join(passed)}")
        if failed:
            summary_parts.append(
                f"{len(failed)} host(s) failed: "
                + ", ".join(f"{f['host']} ({f['error']})" for f in failed)
            )

        return ToolResult.ok(
            output=". ".join(summary_parts),
            passed=passed,
            failed=failed,
        )
