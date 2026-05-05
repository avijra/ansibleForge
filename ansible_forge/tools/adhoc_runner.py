"""Run ad-hoc Ansible module commands against hosts without writing a playbook."""

from __future__ import annotations

import asyncio
import functools
import os
import signal
import stat
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.executor import (
    _LIVE_EVENT_TYPES,
    _format_live_event,
    _sigkill_after_delay,
    clean_stale_env,
)
from ansible_forge.tools.secret_check import find_missing_secrets
from ansible_forge.workspace.project_layout import ensure_ansible_cfg

logger = get_logger(__name__)

_DEFAULT_ADHOC_TIMEOUT = 300
_MAX_ADHOC_TIMEOUT = 7200


def _adhoc_envvars() -> dict[str, str]:
    import sys

    return {
        "ANSIBLE_PYTHON_INTERPRETER": sys.executable,
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
    }


def _kill_runner(runner: Any) -> None:
    """Terminate ansible-runner's subprocess tree, escalating to SIGKILL."""
    import contextlib
    import threading

    with contextlib.suppress(Exception):
        if hasattr(runner, "process") and runner.process and runner.process.pid:
            pid = runner.process.pid
            try:
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                logger.debug("sigterm_pgid_failed", pid=pid, exc_info=True)
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGTERM)

            t = threading.Thread(target=_sigkill_after_delay, args=(pid,), daemon=True)
            t.start()

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
            "Set timeout based on expected duration — default 5 minutes, max 2 hours. "
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
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Max seconds to wait. Default: 300 (5 min). Set higher "
                        "for long-running commands (e.g. installers, builds). "
                        "Max: 7200 (2 hours)."
                    ),
                    "minimum": 10,
                    "maximum": 7200,
                },
                "forks": {
                    "type": "integer",
                    "description": "Number of parallel processes (default: 5)",
                    "minimum": 1,
                    "maximum": 50,
                },
                "verbosity": {
                    "type": "integer",
                    "description": "Verbosity level 0-4 (default: 0)",
                    "minimum": 0,
                    "maximum": 4,
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
        timeout: int = 0,
        forks: int = 0,
        verbosity: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not module or not inventory:
            return ToolResult.fail("workspace_path, module, and inventory are required")

        ws = Path(workspace_path)
        local_targets = {"localhost", "127.0.0.1", "::1", "local"}
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            if host_pattern in local_targets:
                inv_path.parent.mkdir(parents=True, exist_ok=True)
                inv_path.write_text(
                    "[local]\nlocalhost ansible_connection=local\n"
                )
                host_pattern = "localhost"
                logger.info("auto_created_localhost_inventory", path=str(inv_path))
            else:
                return ToolResult.fail(f"Inventory not found: {inv_path}")

        merged_vars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            merged_vars.update(vault.get_all())
        if extra_vars:
            merged_vars.update(extra_vars)
        self._materialize_ssh_keys(ws, merged_vars)
        clean_stale_env(ws)
        ensure_ansible_cfg(ws)
        (ws / ".tuyere").mkdir(parents=True, exist_ok=True)

        if host_pattern not in local_targets:
            missing = find_missing_secrets(inv_path, merged_vars)
            if missing:
                return ToolResult.fail(
                    f"Inventory references secrets not in the vault: {', '.join(missing)}. "
                    f"Use request_secret to collect them from the user before retrying."
                )

        envvars = _adhoc_envvars()
        for key, value in merged_vars.items():
            if key.isupper() or key.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                envvars[key] = str(value)

        live_queue: asyncio.Queue[dict[str, Any]] | None = kwargs.pop("_live_log_queue", None)

        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(ws / ".tuyere"),
            "project_dir": str(ws),
            "module": module,
            "host_pattern": host_pattern,
            "inventory": str(inv_path),
            "envvars": envvars,
        }

        if live_queue is not None:
            import contextlib as _ctxlib

            loop_ref = asyncio.get_event_loop()

            def _on_event(event: dict[str, Any]) -> bool:
                ev_type = event.get("event", "")
                if ev_type in _LIVE_EVENT_TYPES:
                    formatted = _format_live_event(event)
                    if formatted:
                        with _ctxlib.suppress(Exception):
                            loop_ref.call_soon_threadsafe(live_queue.put_nowait, formatted)
                return True

            runner_kwargs["event_handler"] = _on_event
        if module_args:
            runner_kwargs["module_args"] = module_args
        if merged_vars:
            runner_kwargs["extravars"] = merged_vars

        cmdline_parts: list[str] = []
        if become:
            cmdline_parts.append("--become")
        if forks and forks > 0:
            cmdline_parts.extend(["--forks", str(forks)])
        if cmdline_parts:
            runner_kwargs["cmdline"] = " ".join(cmdline_parts)
        if verbosity:
            runner_kwargs["verbosity"] = verbosity

        effective_timeout = min(
            timeout if timeout and timeout > 0 else _DEFAULT_ADHOC_TIMEOUT,
            _MAX_ADHOC_TIMEOUT,
        )

        loop = asyncio.get_event_loop()
        thread, runner = await loop.run_in_executor(
            None,
            functools.partial(ansible_runner.run_async, **runner_kwargs),
        )
        try:
            await asyncio.wait_for(
                loop.run_in_executor(None, thread.join),
                timeout=effective_timeout,
            )
        except asyncio.CancelledError:
            runner.canceled = True
            _kill_runner(runner)
            thread.join(timeout=10)
            logger.info("adhoc_cancelled", module=module, host_pattern=host_pattern)
            raise
        except TimeoutError:
            runner.canceled = True
            _kill_runner(runner)
            thread.join(timeout=10)
            mins = effective_timeout // 60
            secs = effective_timeout % 60
            time_str = f"{mins}m{secs}s" if secs else f"{mins} minute(s)"
            return ToolResult.fail(
                f"Command timed out after {time_str}. "
                f"If this operation legitimately needs more time, retry with a "
                f"higher timeout parameter."
            )
        result = runner

        host_results: dict[str, Any] = {}
        runner_errors: list[str] = []
        for event in result.events:
            ev_type = event.get("event", "")
            event_data = event.get("event_data", {})
            if ev_type in ("runner_on_ok", "runner_on_changed", "runner_on_failed",
                           "runner_on_unreachable", "runner_on_skipped"):
                host = event_data.get("host", "unknown")
                res = event_data.get("res", {})
                host_results[host] = {
                    "status": ev_type.replace("runner_on_", ""),
                    "changed": res.get("changed", False),
                    "msg": res.get("msg", ""),
                    "stdout": (res.get("stdout", "") or "")[:2000],
                    "stderr": (res.get("stderr", "") or "")[:1000],
                    "rc": res.get("rc"),
                }
            elif ev_type == "runner_on_no_hosts":
                runner_errors.append(
                    f"No hosts matched pattern '{host_pattern}' in inventory."
                )
            elif ev_type == "error" or ev_type == "verbose":
                stderr = event_data.get("data", "")
                if stderr and len(str(stderr)) > 5:
                    runner_errors.append(str(stderr)[:500])

        if not host_results:
            detail = " ".join(runner_errors) if runner_errors else ""
            return ToolResult.fail(
                f"No hosts responded for pattern '{host_pattern}'. "
                f"{detail} "
                f"Check that the inventory file contains matching hosts and "
                f"the host_pattern is correct. If targeting localhost, ensure "
                f"the inventory has 'ansible_connection=local' set."
            )

        ok = sum(1 for r in host_results.values() if r["status"] in ("ok", "changed"))
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
