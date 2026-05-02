"""Run ad-hoc Ansible module commands against hosts without writing a playbook."""

from __future__ import annotations

import asyncio
import functools
import os
import stat
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.secret_check import find_missing_secrets

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


class AdhocRunner(BaseTool):
    @property
    def name(self) -> str:
        return "run_adhoc"

    @property
    def description(self) -> str:
        return (
            "Run an ad-hoc Ansible module command against one or more hosts without "
            "writing a playbook. Useful for quick one-off tasks like restarting a "
            "service, checking disk space, managing packages, or running shell commands. "
            "Requires workspace with inventory already configured."
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
                "module": {
                    "type": "string",
                    "description": (
                        "Ansible module FQCN to run (e.g. 'ansible.builtin.shell', "
                        "'ansible.builtin.service', 'ansible.builtin.apt')"
                    ),
                },
                "module_args": {
                    "type": "string",
                    "description": (
                        "Module arguments as a string (e.g. 'name=nginx state=restarted' "
                        "or 'df -h' for shell)"
                    ),
                },
                "host_pattern": {
                    "type": "string",
                    "description": "Host or group pattern to target (e.g. 'all', 'webservers', '10.0.0.5')",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "become": {
                    "type": "boolean",
                    "description": "Whether to use privilege escalation (sudo). Default: false",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Extra variables to pass",
                    "additionalProperties": {},
                },
            },
            "required": ["workspace_path", "module", "host_pattern", "inventory"],
        }

    @staticmethod
    def _materialize_ssh_keys(ws: Path, merged_vars: dict[str, Any]) -> list[Path]:
        files: list[Path] = []
        keys_dir = ws / ".tuyere" / "ssh_keys"
        for var_name in list(merged_vars):
            value = merged_vars[var_name]
            if not isinstance(value, str):
                continue
            is_key = (
                var_name.lower() in _SSH_KEY_SECRET_NAMES
                or all(h in value for h in _SSH_KEY_HEADERS)
            )
            if not is_key:
                continue
            keys_dir.mkdir(parents=True, exist_ok=True)
            key_file = keys_dir / var_name
            if key_file.exists():
                os.chmod(key_file, stat.S_IWUSR | stat.S_IRUSR)
            key_file.write_text(value)
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
            merged_vars[var_name] = str(key_file)
            files.append(key_file)
        return files

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
        module: str = "",
        module_args: str = "",
        host_pattern: str = "all",
        inventory: str = "",
        become: bool = False,
        extra_vars: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not module or not inventory:
            return ToolResult.fail("workspace_path, module, and inventory are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        merged_vars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            merged_vars.update(vault.get_all())
        if extra_vars:
            merged_vars.update(extra_vars)
        self._materialize_ssh_keys(ws, merged_vars)

        if host_pattern != "localhost":
            missing = find_missing_secrets(inv_path, merged_vars)
            if missing:
                return ToolResult.fail(
                    f"Inventory references secrets not in the vault: {', '.join(missing)}. "
                    f"Use request_secret to collect them from the user before retrying."
                )

        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(ws / ".tuyere"),
            "module": module,
            "host_pattern": host_pattern,
            "inventory": str(inv_path),
        }
        if module_args:
            runner_kwargs["module_args"] = module_args
        if merged_vars:
            runner_kwargs["extravars"] = merged_vars
        if become:
            runner_kwargs["cmdline"] = "--become"

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, functools.partial(ansible_runner.run, **runner_kwargs)
                ),
                timeout=120,
            )
        except TimeoutError:
            return ToolResult.fail(
                "Command timed out after 2 minutes. "
                "The host may be unresponsive or the command is taking longer than expected."
            )

        host_results: dict[str, Any] = {}
        for event in result.events:
            ev_type = event.get("event", "")
            if ev_type in ("runner_on_ok", "runner_on_failed", "runner_on_unreachable"):
                host = event.get("event_data", {}).get("host", "unknown")
                res = event.get("event_data", {}).get("res", {})
                host_results[host] = {
                    "status": ev_type.replace("runner_on_", ""),
                    "changed": res.get("changed", False),
                    "msg": res.get("msg", ""),
                    "stdout": (res.get("stdout", "") or "")[:2000],
                    "stderr": (res.get("stderr", "") or "")[:1000],
                    "rc": res.get("rc"),
                }

        if not host_results:
            return ToolResult.fail(
                "No hosts responded. "
                "Verify that your server list is correct and hosts are reachable."
            )

        ok = sum(1 for r in host_results.values() if r["status"] == "ok")
        failed = sum(1 for r in host_results.values() if r["status"] == "failed")
        unreachable = sum(1 for r in host_results.values() if r["status"] == "unreachable")

        total = len(host_results)

        if failed or unreachable:
            parts = []
            if failed:
                parts.append(f"{failed} failed")
            if unreachable:
                parts.append(f"{unreachable} unreachable")
            if ok:
                parts.append(f"{ok} succeeded")
            return ToolResult.fail(
                f"Command finished on {total} host(s) with issues: {', '.join(parts)}.",
                host_results=host_results,
                module=module,
                module_args=module_args,
            )

        return ToolResult.ok(
            output=f"Command completed on {total} host(s) — all successful.",
            host_results=host_results,
            module=module,
            module_args=module_args,
        )
