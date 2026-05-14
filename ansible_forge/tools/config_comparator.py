"""Compare configuration files across multiple hosts to find inconsistencies."""

from __future__ import annotations

import asyncio
import difflib
import functools
import os
import stat
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.executor import isolated_runner_dir

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


class ConfigComparator(BaseTool):
    @property
    def name(self) -> str:
        return "compare_configs"

    @property
    def description(self) -> str:
        return (
            "Fetch a configuration file from multiple hosts and diff them to find "
            "inconsistencies. Uses ansible.builtin.slurp to securely retrieve file "
            "contents and produces a unified diff between hosts. Useful for verifying "
            "configuration consistency across a fleet."
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
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file on the remote hosts (e.g. '/etc/ssh/sshd_config')",
                },
                "host_pattern": {
                    "type": "string",
                    "description": "Host or group pattern to compare across (e.g. 'webservers', 'all')",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "become": {
                    "type": "boolean",
                    "description": "Use privilege escalation to read the file (default: false)",
                },
            },
            "required": ["workspace_path", "file_path", "host_pattern", "inventory"],
        }

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
        file_path: str = "",
        host_pattern: str = "all",
        inventory: str = "",
        become: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not file_path or not inventory:
            return ToolResult.fail("workspace_path, file_path, and inventory are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())

        keys_dir = ws / ".tuyere" / "ssh_keys"
        for var_name in list(extravars):
            value = extravars[var_name]
            if not isinstance(value, str):
                continue
            if var_name.lower() in _SSH_KEY_SECRET_NAMES or all(h in value for h in _SSH_KEY_HEADERS):
                keys_dir.mkdir(parents=True, exist_ok=True)
                key_file = keys_dir / var_name
                if key_file.exists():
                    os.chmod(key_file, stat.S_IWUSR | stat.S_IRUSR)
                key_file.write_text(value)
                os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
                extravars[var_name] = str(key_file)

        with isolated_runner_dir(ws) as run_dir:
            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "module": "ansible.builtin.slurp",
                "module_args": f"src={file_path}",
                "host_pattern": host_pattern,
                "inventory": str(inv_path),
            }
            if extravars:
                runner_kwargs["extravars"] = extravars
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
                return ToolResult.fail("Config fetch timed out after 2 minutes.")

            import base64
            host_contents: dict[str, str] = {}
            errors: dict[str, str] = {}

            for event in result.events:
                ev_type = event.get("event", "")
                ed = event.get("event_data", {})
                host = ed.get("host", "unknown")

                if ev_type == "runner_on_ok":
                    res = ed.get("res", {})
                    encoded = res.get("content", "")
                    try:
                        host_contents[host] = base64.b64decode(encoded).decode("utf-8", errors="replace")
                    except Exception as exc:
                        errors[host] = f"Failed to decode: {exc}"
                elif ev_type in ("runner_on_failed", "runner_on_unreachable"):
                    res = ed.get("res", {})
                    errors[host] = res.get("msg", "Failed to fetch file")

        if not host_contents:
            return ToolResult.fail(
                f"Could not fetch '{file_path}' from any host. Errors: {errors}"
            )

        if len(host_contents) < 2:
            host = list(host_contents.keys())[0]
            return ToolResult.ok(
                output=f"Only retrieved '{file_path}' from 1 host ({host}). Need at least 2 hosts to compare.",
                host_contents={host: host_contents[host][:5000]},
                errors=errors,
            )

        hosts = sorted(host_contents.keys())
        reference_host = hosts[0]
        reference_content = host_contents[reference_host]
        ref_lines = reference_content.splitlines(keepends=True)

        diffs: dict[str, dict[str, Any]] = {}
        identical_hosts: list[str] = [reference_host]

        for host in hosts[1:]:
            content = host_contents[host]
            if content == reference_content:
                identical_hosts.append(host)
                diffs[host] = {"identical": True, "diff": ""}
                continue

            host_lines = content.splitlines(keepends=True)
            diff = difflib.unified_diff(
                ref_lines, host_lines,
                fromfile=f"{reference_host}:{file_path}",
                tofile=f"{host}:{file_path}",
                lineterm="",
            )
            diff_text = "\n".join(diff)
            diffs[host] = {
                "identical": False,
                "diff": diff_text[:5000],
                "line_count_ref": len(ref_lines),
                "line_count_host": len(host_lines),
            }

        different_count = sum(1 for d in diffs.values() if not d.get("identical"))

        return ToolResult.ok(
            output=(
                f"Compared '{file_path}' across {len(host_contents)} hosts. "
                f"{len(identical_hosts)} identical, {different_count} different."
            ),
            reference_host=reference_host,
            identical_hosts=identical_hosts,
            diffs=diffs,
            errors=errors,
            file_path=file_path,
        )
