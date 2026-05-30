"""Run ad-hoc Ansible module commands against hosts without writing a playbook."""

from __future__ import annotations

import asyncio
import functools
import os
import signal
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus
from ansible_forge.tools.executor import (
    _LIVE_EVENT_TYPES,
    _format_live_event,
    _resolve_python_interpreter,
    _sigkill_after_delay,
    isolated_runner_dir,
    materialize_ssh_keys,
)
from ansible_forge.tools.secret_check import find_missing_secrets
from ansible_forge.workspace.project_layout import ensure_ansible_cfg

logger = get_logger(__name__)

_DEFAULT_ADHOC_TIMEOUT = 300
_MAX_ADHOC_TIMEOUT = 7200

_STDOUT_TAIL_INTERVAL = 2.0
_STDOUT_TAIL_MAX_LINE = 500
_STDOUT_MODULES = frozenset({"ansible.builtin.shell", "ansible.builtin.command", "shell", "command"})


def _localhost_inventory_content() -> str:
    """Build localhost inventory with the best available Python interpreter."""
    interp = _resolve_python_interpreter()
    if interp and interp != "auto_silent":
        return (
            f"[local]\nlocalhost ansible_connection=local"
            f" ansible_python_interpreter={interp}\n"
        )
    return "[local]\nlocalhost ansible_connection=local\n"


def _adhoc_envvars() -> dict[str, str]:
    import sys

    envvars: dict[str, str] = {
        "ANSIBLE_PYTHON_INTERPRETER": _resolve_python_interpreter(),
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        "LC_ALL": "en_US.UTF-8",
        "LANG": "en_US.UTF-8",
    }

    if getattr(sys, "frozen", False):
        envvars["PYTHONHOME"] = ""
        envvars["PYTHONPATH"] = ""

    return envvars


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

async def _tail_runner_stdout(
    run_dir: Path, queue: asyncio.Queue[dict[str, Any]]
) -> None:
    """Poll the ansible-runner artifacts stdout file and emit new lines as live_log events.

    For shell/command modules the only Ansible events are play_start, task_start,
    and the final result.  This fills the gap by streaming raw subprocess output.
    """
    import contextlib

    artifacts = run_dir / "artifacts"
    stdout_file: Path | None = None
    pos = 0

    while True:
        await asyncio.sleep(_STDOUT_TAIL_INTERVAL)
        try:
            if stdout_file is None:
                if not artifacts.is_dir():
                    continue
                for child in artifacts.iterdir():
                    candidate = child / "stdout"
                    if candidate.is_file():
                        stdout_file = candidate
                        break
                if stdout_file is None:
                    continue

            try:
                size = stdout_file.stat().st_size
            except OSError:
                continue
            if size <= pos:
                continue

            with stdout_file.open("r", encoding="utf-8", errors="replace") as fh:
                fh.seek(pos)
                chunk = fh.read(16384)
                pos = fh.tell()

            if not chunk.strip():
                continue

            lines = chunk.strip().splitlines()
            for line in lines[-20:]:
                trimmed = line[:_STDOUT_TAIL_MAX_LINE]
                if trimmed.strip():
                    with contextlib.suppress(Exception):
                        queue.put_nowait({
                            "type": "shell_output",
                            "line": trimmed,
                        })
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


_DESTRUCTIVE_STATES = {"absent", "stopped", "removed", "purged", "killed", "dead"}

_DESTRUCTIVE_MODULES = frozenset({
    "ansible.builtin.file", "ansible.builtin.user", "ansible.builtin.group",
    "ansible.builtin.apt", "ansible.builtin.yum", "ansible.builtin.dnf",
    "ansible.builtin.pip", "ansible.builtin.service", "ansible.builtin.systemd",
    "ansible.builtin.cron", "file", "user", "group", "apt", "yum", "dnf",
    "pip", "service", "systemd", "cron",
})


def _is_destructive_adhoc(module: str, module_args: str) -> bool:
    if module not in _DESTRUCTIVE_MODULES:
        return False
    args_lower = module_args.lower()
    return any(f"state={s}" in args_lower for s in _DESTRUCTIVE_STATES)


_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")

_BLOCKED_ADHOC_MODULES = frozenset({
    "shell", "command", "raw", "script",
    "ansible.builtin.shell", "ansible.builtin.command",
    "ansible.builtin.raw", "ansible.builtin.script",
})


class AdhocRunner(BaseTool):
    @property
    def name(self) -> str:
        return "run_adhoc"

    @property
    def description(self) -> str:
        return (
            "Run a DIAGNOSTIC ad-hoc Ansible module against hosts. Allowed modules: "
            "ping, setup, stat, find, debug, assert, gather_facts, k8s_info, "
            "ec2_instance_info, and other *_info read-only modules. "
            "shell/command/raw/script are BLOCKED — write a playbook instead. "
            "For any mutating operation, use execute_playbook with a proper playbook "
            "that includes idempotency guards (creates:, when:, changed_when:). "
            "Set check_mode=true to preview changes. Default timeout: 5 min. Max: 2 hours."
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
                "check_mode": {
                    "type": "boolean",
                    "description": (
                        "Dry-run mode: preview what the module WOULD change without "
                        "making actual changes (--check --diff). Use before applying "
                        "changes to packages, services, files, or users. Returns "
                        "NEEDS_APPROVAL on success so you can review before applying."
                    ),
                },
            },
            "required": ["workspace_path", "module", "host_pattern", "inventory"],
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
        module: str = "",
        module_args: str = "",
        host_pattern: str = "all",
        inventory: str = "",
        become: bool = False,
        extra_vars: dict[str, Any] | None = None,
        timeout: int = 0,
        forks: int = 0,
        verbosity: int = 0,
        check_mode: bool = False,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not module or not inventory:
            return ToolResult.fail("workspace_path, module, and inventory are required")

        if module.strip() in _BLOCKED_ADHOC_MODULES:
            return ToolResult.fail(
                f"Ad-hoc '{module}' is not allowed. Write a playbook instead.\n\n"
                "run_adhoc is for diagnostic Ansible modules only (ping, setup, stat, "
                "find, debug, k8s_info, ec2_instance_info, etc.).\n"
                "For shell commands, write a playbook with ansible.builtin.command "
                "and appropriate guards (creates:, when:), then use execute_playbook."
            )

        ws = Path(workspace_path)
        local_targets = {"localhost", "127.0.0.1", "::1", "local"}
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            if host_pattern in local_targets:
                inv_path.parent.mkdir(parents=True, exist_ok=True)
                inv_path.write_text(_localhost_inventory_content())
                host_pattern = "localhost"
                logger.info("auto_created_localhost_inventory", path=str(inv_path))
            else:
                return ToolResult.fail(f"Inventory not found: {inv_path}")

        merged_vars: dict[str, Any] = {}
        vault_keys: set[str] = set()
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            vault_secrets = vault.get_all()
            merged_vars.update(vault_secrets)
            vault_keys = set(vault_secrets.keys())
        if extra_vars:
            merged_vars.update(extra_vars)
        ensure_ansible_cfg(ws)
        (ws / ".tuyere").mkdir(parents=True, exist_ok=True)

        if host_pattern not in local_targets:
            missing = find_missing_secrets(inv_path, merged_vars)
            if missing:
                return ToolResult.fail(
                    f"Inventory references secrets not in the vault: {', '.join(missing)}. "
                    f"Use request_secret to collect them from the user before retrying."
                )

        if not check_mode and _is_destructive_adhoc(module, module_args):
            return ToolResult(
                status=ToolStatus.NEEDS_APPROVAL,
                output=(
                    f"Destructive operation detected: `{module}` with args "
                    f"matching a destructive state (absent/stopped/removed/purged). "
                    f"Approve to proceed, or re-run with check_mode=true to preview."
                ),
                data={
                    "module": module,
                    "module_args": module_args[:500],
                    "risk_level": "high",
                    "destructive": True,
                },
            )

        if host_pattern in local_targets and "ansible_python_interpreter" not in merged_vars:
            interp = _resolve_python_interpreter()
            if interp and interp != "auto_silent":
                merged_vars["ansible_python_interpreter"] = interp

        live_queue: asyncio.Queue[dict[str, Any]] | None = kwargs.pop("_live_log_queue", None)

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", merged_vars)

            envvars = _adhoc_envvars()
            for key, value in merged_vars.items():
                if key.isupper() or key.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                    envvars[key] = str(value)
            for key in vault_keys:
                upper = key.upper()
                if upper != key and upper not in envvars:
                    envvars[upper] = str(merged_vars[key])
            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "project_dir": str(ws),
                "module": module,
                "host_pattern": host_pattern,
                "inventory": str(inv_path),
                "envvars": envvars,
            }

            if live_queue is not None:
                import contextlib as _ctxlib

                loop_ref = asyncio.get_running_loop()

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
            if check_mode:
                cmdline_parts.extend(["--check", "--diff"])
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

            is_shell_module = module.split(".")[-1] in ("shell", "command")
            stdout_tailer: asyncio.Task[None] | None = None
            log_watcher: asyncio.Task[None] | None = None

            loop = asyncio.get_running_loop()
            thread, runner = await loop.run_in_executor(
                None,
                functools.partial(ansible_runner.run_async, **runner_kwargs),
            )

            if is_shell_module and live_queue is not None:
                stdout_tailer = asyncio.create_task(
                    _tail_runner_stdout(run_dir, live_queue)
                )
                from ansible_forge.tools._log_tailer import snapshot_log_files, tail_new_logs
                log_snapshot = snapshot_log_files(ws)
                log_watcher = asyncio.create_task(
                    tail_new_logs(ws, log_snapshot, live_queue)
                )

            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, thread.join),
                    timeout=effective_timeout,
                )
            except asyncio.CancelledError:
                runner.canceled = True
                _kill_runner(runner)
                await loop.run_in_executor(None, lambda: thread.join(timeout=10))
                logger.info("adhoc_cancelled", module=module, host_pattern=host_pattern)
                raise
            except TimeoutError:
                runner.canceled = True
                _kill_runner(runner)
                await loop.run_in_executor(None, lambda: thread.join(timeout=10))
                mins = effective_timeout // 60
                secs = effective_timeout % 60
                time_str = f"{mins}m{secs}s" if secs else f"{mins} minute(s)"
                return ToolResult.fail(
                    f"Command timed out after {time_str}. "
                    f"If this operation legitimately needs more time, retry with a "
                    f"higher timeout parameter."
                )
            finally:
                import contextlib as _ctxlib2
                for _task in (stdout_tailer, log_watcher):
                    if _task and not _task.done():
                        _task.cancel()
                        with _ctxlib2.suppress(asyncio.CancelledError):
                            await _task

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

            if check_mode:
                return ToolResult(
                    status=ToolStatus.NEEDS_APPROVAL,
                    output=(
                        f"Dry-run preview completed on {total} host(s) — no changes made. "
                        f"Review the results above, then re-run without check_mode to apply."
                    ),
                    data={
                        "host_results": host_results,
                        "module": module,
                        "module_args": module_args,
                        "mode": "check",
                    },
                )

            return ToolResult.ok(
                output=f"Command completed on {total} host(s) — all successful.",
                host_results=host_results,
                module=module,
                module_args=module_args,
            )
