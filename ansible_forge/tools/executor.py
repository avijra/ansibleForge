"""Execute Ansible playbooks via ansible-runner with check-mode and apply support."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import shutil
import signal
import stat
import uuid
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools._log_tailer import (
    detect_new_log_files as _detect_new_log_files,
)
from ansible_forge.tools._log_tailer import (
    snapshot_log_files as _snapshot_log_files,
)
from ansible_forge.tools._log_tailer import (
    tail_new_logs as _tail_new_logs,
)
from ansible_forge.tools._runner_diagnostics import (
    diagnose_runner_failure,
    read_runner_stdout,
)
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus
from ansible_forge.tools.ee_runtime import runner_locale_env
from ansible_forge.tools.secret_check import find_missing_secrets
from ansible_forge.workspace.project_layout import ensure_ansible_cfg

logger = get_logger(__name__)

_DEFAULT_PLAYBOOK_TIMEOUT = 3600
_MAX_PLAYBOOK_TIMEOUT = 86400


def _resolve_python_interpreter() -> str:
    """Return a Python interpreter path suitable for ANSIBLE_PYTHON_INTERPRETER.

    Uses resolve_or_install which downloads a standalone CPython 3.12 via uv
    if not already present.  The result is cached module-wide so only the
    first call can be slow.
    """
    from ansible_forge.tools.python_resolver import resolve_or_install_python_for_localhost

    return resolve_or_install_python_for_localhost()


def _runner_envvars() -> dict[str, str]:
    """Environment variables passed to ansible-runner for every invocation.

    In frozen (PyInstaller) mode, strips vars that would interfere with the
    standalone Python used for module execution on localhost. In EE mode the
    host interpreter path is never injected — the container has its own Python.
    """
    import sys

    from ansible_forge.tools.ee_runtime import is_ee_enabled

    envvars: dict[str, str] = {
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_STDOUT_CALLBACK": "json",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        **runner_locale_env(),
    }
    if not is_ee_enabled():
        envvars["ANSIBLE_PYTHON_INTERPRETER"] = _resolve_python_interpreter()

    if getattr(sys, "frozen", False):
        envvars["PYTHONHOME"] = ""
        envvars["PYTHONPATH"] = ""

    return envvars

_CAPTURE_EVENT_TYPES = frozenset({
    "runner_on_ok", "runner_on_failed", "runner_on_skipped",
    "runner_on_changed", "runner_on_unreachable",
})


def parse_json_stdout_events(runner_result: Any) -> list[dict[str, Any]]:
    """Extract ansible-runner-style events from the JSON stdout callback output.

    ansible-runner's ``awx_display`` callback frequently fails to write
    ``runner_on_ok/failed`` event files (observed across versions and in
    PyInstaller builds).  The JSON stdout callback
    (``ANSIBLE_STDOUT_CALLBACK=json``) always produces a structured blob we
    can parse to reconstruct events reliably.

    The raw stdout may contain Ansible warning lines and ANSI escape sequences
    from ``awx_display``; both are stripped before JSON extraction.
    """
    import json as _json
    import re as _re

    raw = (
        runner_result.stdout.read()
        if hasattr(runner_result.stdout, "read")
        else str(runner_result.stdout or "")
    )
    if hasattr(runner_result.stdout, "seek"):
        runner_result.stdout.seek(0)
    if not raw or not raw.strip():
        return []

    cleaned = _re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)

    try:
        data = _json.loads(cleaned)
    except (ValueError, TypeError):
        idx = cleaned.find("\n{")
        if idx < 0:
            return []
        try:
            data = _json.loads(cleaned[idx + 1:])
        except (ValueError, TypeError):
            return []

    if not isinstance(data, dict) or "plays" not in data:
        return []

    events: list[dict[str, Any]] = []
    for play in data.get("plays", []):
        for task_entry in play.get("tasks", []):
            task_info = task_entry.get("task", {})
            task_name = task_info.get("name", "")
            hosts = task_entry.get("hosts", {})
            for host, res in hosts.items():
                if not isinstance(res, dict):
                    continue
                if res.get("unreachable"):
                    etype = "runner_on_unreachable"
                elif res.get("failed"):
                    etype = "runner_on_failed"
                elif res.get("skipped"):
                    etype = "runner_on_skipped"
                elif res.get("changed"):
                    etype = "runner_on_changed"
                else:
                    etype = "runner_on_ok"

                events.append({
                    "event": etype,
                    "event_data": {
                        "host": host,
                        "task": task_name,
                        "res": res,
                    },
                })

    if not events:
        stats = data.get("stats", {})
        for host, counts in stats.items():
            if not isinstance(counts, dict):
                continue
            if counts.get("unreachable", 0) > 0:
                etype = "runner_on_unreachable"
            elif counts.get("failures", 0) > 0:
                etype = "runner_on_failed"
            elif counts.get("ok", 0) > 0 or counts.get("changed", 0) > 0:
                etype = "runner_on_ok"
            else:
                continue
            events.append({
                "event": etype,
                "event_data": {"host": host, "task": "", "res": {}},
            })

    return events


def get_runner_events(runner_result: Any) -> list[dict[str, Any]]:
    """Return runner events, preferring JSON stdout parsing.

    ansible-runner's ``awx_display`` callback reliably writes ``runner_on_start``
    events but often omits ``runner_on_ok/failed/changed`` events in modern
    Ansible versions.  The JSON stdout callback always produces complete data,
    so we prefer it and only fall back to ``result.events`` when stdout parsing
    yields nothing.
    """
    parsed = parse_json_stdout_events(runner_result)
    if parsed:
        return parsed
    return list(runner_result.events or [])

_LIVE_EVENT_TYPES = frozenset({
    "playbook_on_play_start",
    "playbook_on_task_start",
    "runner_on_ok",
    "runner_on_changed",
    "runner_on_failed",
    "runner_on_skipped",
    "runner_on_unreachable",
    "playbook_on_stats",
})


def _format_live_event(event: dict[str, Any]) -> dict[str, Any] | None:
    ev_type = event.get("event", "")
    ev_data = event.get("event_data", {})

    if ev_type == "playbook_on_play_start":
        name = ev_data.get("name", "")
        if not name:
            play = ev_data.get("play", "")
            name = play if isinstance(play, str) else ""
        return {"type": "play_start", "play": name}

    if ev_type == "playbook_on_task_start":
        task = ev_data.get("name", "") or ev_data.get("task", "")
        return {"type": "task_start", "task": task}

    if ev_type in ("runner_on_ok", "runner_on_changed"):
        res = ev_data.get("res", {})
        return {
            "type": "task_ok",
            "host": ev_data.get("host", ""),
            "task": ev_data.get("task", ""),
            "changed": res.get("changed", ev_type == "runner_on_changed"),
        }

    if ev_type == "runner_on_failed":
        res = ev_data.get("res", {})
        msg = res.get("msg", "") or res.get("stderr", "")
        return {
            "type": "task_failed",
            "host": ev_data.get("host", ""),
            "task": ev_data.get("task", ""),
            "error": str(msg)[:500],
        }

    if ev_type == "runner_on_skipped":
        return {
            "type": "task_skipped",
            "host": ev_data.get("host", ""),
            "task": ev_data.get("task", ""),
        }

    if ev_type == "runner_on_unreachable":
        return {
            "type": "host_unreachable",
            "host": ev_data.get("host", ""),
            "task": ev_data.get("task", ""),
        }

    if ev_type == "playbook_on_stats":
        return {"type": "stats", "stats": ev_data}

    return None


def _sigkill_after_delay(pid: int, delay: float = 10.0) -> None:
    """Background thread: wait, then SIGKILL if still alive."""
    import contextlib
    import time as _time

    _time.sleep(delay)
    try:
        os.kill(pid, 0)
        logger.warning("sigkill_escalation", pid=pid)
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


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


def kill_stale_runner_procs(private_data_dir: str | Path) -> None:
    """Kill any ansible-runner child processes left after a timeout.

    Scans the artifacts directory for PID files and sends SIGTERM/SIGKILL.
    """
    import contextlib
    import threading

    artifacts = Path(private_data_dir) / "artifacts"
    if not artifacts.is_dir():
        return
    for pid_file in artifacts.rglob("pid"):
        try:
            pid = int(pid_file.read_text().strip())
        except (ValueError, OSError):
            continue
        with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
        t = threading.Thread(target=_sigkill_after_delay, args=(pid,), daemon=True)
        t.start()


def clean_stale_env(ws: Path) -> None:
    """Remove env artifacts left by prior ansible-runner invocations.

    ansible-runner's ``dump_artifacts`` writes parameters like *cmdline*
    and *extravars* to ``env/`` **only when the file does not already
    exist**.  On subsequent runs, if the caller omits a parameter (e.g.
    ``cmdline`` is empty in apply mode), runner falls back to reading
    the stale file — which may still contain ``--check --diff`` from a
    previous dry-run.  Cleaning these files before every run ensures
    the correct flags are always used.
    """
    env_dir = ws / ".tuyere" / "env"
    if not env_dir.exists():
        return
    for artifact in ("cmdline", "extravars"):
        path = env_dir / artifact
        if path.exists():
            try:
                path.unlink()
            except OSError:
                logger.debug("clean_stale_env_unlink_failed", path=str(path), exc_info=True)


@contextlib.contextmanager
def isolated_runner_dir(ws: Path):
    """Yield an isolated private_data_dir for ansible-runner.

    Each invocation gets ``ws/.tuyere/runs/<uuid>/`` with a pre-created
    ``env/`` subdirectory.  This prevents the .artifact_write_lock race
    condition that occurs when parallel runner calls share the same
    private_data_dir.  The directory is removed when the context exits.
    """
    runs_root = ws / ".tuyere" / "runs"
    _purge_orphan_runs(runs_root)
    run_dir = runs_root / uuid.uuid4().hex[:12]
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "env").mkdir(exist_ok=True)
    try:
        yield run_dir
    finally:
        with contextlib.suppress(OSError):
            shutil.rmtree(run_dir, ignore_errors=True)


_ORPHAN_MAX_AGE_SECS = 3600


def _purge_orphan_runs(runs_root: Path) -> None:
    """Remove run directories older than 1 hour (leftovers from crashed runs)."""
    if not runs_root.is_dir():
        return
    import time

    now = time.time()
    for entry in runs_root.iterdir():
        if not entry.is_dir():
            continue
        try:
            age = now - entry.stat().st_mtime
            if age > _ORPHAN_MAX_AGE_SECS:
                shutil.rmtree(entry, ignore_errors=True)
                logger.debug("purged_orphan_run_dir", path=str(entry), age_secs=int(age))
        except OSError:
            pass


_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


def materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
    """Write SSH key secrets to disk inside the given directory.

    Scans ``merged_vars`` for values that look like SSH private keys
    (by variable name or content).  Each match is written with 0600
    permissions and the variable value is replaced with the file path.
    """
    files: list[Path] = []
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
        logger.info("ssh_key_materialized", variable=var_name, path=str(key_file))
    return files


def _inject_python_interpreter(
    ws: Path, playbook: str, merged_vars: dict[str, Any],
) -> None:
    """Inject ansible_python_interpreter into extravars when targeting localhost.

    Extravars have the highest precedence in Ansible (higher than ansible.cfg,
    inventory host_vars, and environment variables), so this prevents any
    ansible.cfg `interpreter_python` setting from overriding the standalone
    Python path that AnsibleForge ships.

    Never injected in EE mode: the host interpreter path does not exist
    inside the container and would break every localhost task.
    """
    from ansible_forge.tools.ee_runtime import is_ee_enabled

    if is_ee_enabled():
        return

    if "ansible_python_interpreter" in merged_vars:
        return

    interp = _resolve_python_interpreter()
    if not interp or interp == "auto_silent":
        return

    playbook_path = ws / playbook
    if not playbook_path.exists():
        return

    try:
        content = playbook_path.read_text(encoding="utf-8")
    except OSError:
        return

    targets_localhost = any(
        marker in content
        for marker in ("localhost", "127.0.0.1", "connection: local", "hosts: all")
    )
    if targets_localhost:
        merged_vars["ansible_python_interpreter"] = interp
        logger.info("injected_python_interpreter_extravar", interpreter=interp)


def _extract_extra_log_dirs(
    ws: Path, merged_vars: dict[str, Any], playbook: str,
) -> list[Path]:
    """Extract directories outside the workspace that might contain logs.

    Scans extravars for values that look like existing absolute directory
    paths, and parses the playbook YAML for ``chdir`` arguments.
    """
    dirs: list[Path] = []
    ws_str = str(ws.resolve())
    for value in merged_vars.values():
        if not isinstance(value, str):
            continue
        if not os.path.isabs(value):
            continue
        p = Path(value)
        if p.is_dir() and not str(p.resolve()).startswith(ws_str + os.sep):
            dirs.append(p)
        elif p.parent.is_dir() and not str(p.parent.resolve()).startswith(ws_str + os.sep):
            dirs.append(p.parent)

    pb_path = ws / playbook
    if pb_path.exists():
        try:
            text = pb_path.read_text(encoding="utf-8", errors="replace")
            import re
            for m in re.finditer(r'chdir:\s*["\']?([^\s"\'#]+)', text):
                chdir_val = m.group(1)
                if os.path.isabs(chdir_val):
                    d = Path(chdir_val)
                    if d.is_dir() and not str(d.resolve()).startswith(ws_str + os.sep):
                        dirs.append(d)
        except OSError:
            pass

    seen: set[str] = set()
    unique: list[Path] = []
    for d in dirs:
        key = str(d.resolve())
        if key not in seen:
            seen.add(key)
            unique.append(d)
    return unique


class Executor(BaseTool):
    @property
    def name(self) -> str:
        return "execute_playbook"

    @property
    def description(self) -> str:
        return (
            "Execute an Ansible playbook using ansible-runner. Supports two modes: "
            "'check' (dry-run with --check --diff to preview changes without applying) "
            "and 'apply' (actually execute changes on target hosts). Supports limit, "
            "tags, skip_tags, start_at_task, forks, timeout, become, and verbosity for "
            "full CLI parity. Default timeout: 1 hour. Max: 24 hours (for long operations "
            "like cluster installs). Estimate timeout from task complexity and host count. "
            "Always prefer 'check' mode first to preview changes before applying."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the project directory",
                },
                "playbook": {
                    "type": "string",
                    "description": "Playbook filename (relative to project directory)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["check", "apply"],
                    "description": "Execution mode: 'check' for dry-run, 'apply' for live execution",
                },
                "inventory": {
                    "type": "string",
                    "description": "Path to inventory file (relative to project's inventory/ directory)",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Extra variables to pass to the playbook",
                    "additionalProperties": {},
                },
                "limit": {
                    "type": "string",
                    "description": "Limit execution to specific hosts/groups",
                },
                "tags": {
                    "type": "string",
                    "description": "Comma-separated tags to run",
                },
                "skip_tags": {
                    "type": "string",
                    "description": "Comma-separated tags to skip",
                },
                "start_at_task": {
                    "type": "string",
                    "description": "Start execution at a specific task name",
                },
                "forks": {
                    "type": "integer",
                    "description": "Number of parallel processes (default: 5)",
                    "minimum": 1,
                    "maximum": 50,
                },
                "timeout": {
                    "type": "integer",
                    "description": (
                        "Max seconds to wait for the playbook to finish. "
                        "Default: 3600 (1 hour). Estimate from task complexity. "
                        "Max: 86400 (24 hours)."
                    ),
                    "minimum": 60,
                    "maximum": 86400,
                },
                "become": {
                    "type": "boolean",
                    "description": "Whether to use privilege escalation (sudo). Default: false. Use when playbook needs root but doesn't set become internally.",
                },
                "verbosity": {
                    "type": "integer",
                    "description": "Verbosity level 0-4 (default: 0)",
                    "minimum": 0,
                    "maximum": 4,
                },
            },
            "required": ["workspace_path", "playbook", "mode"],
        }

    @staticmethod
    def _materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
        """Write SSH key secrets into keys_dir (should be inside isolated run_dir)."""
        return materialize_ssh_keys(keys_dir, merged_vars)

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        """Resolve inventory path, handling cases where the agent includes 'inventory/' prefix."""
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
        playbook: str = "",
        mode: str = "check",
        inventory: str = "",
        extra_vars: dict[str, Any] | None = None,
        limit: str = "",
        tags: str = "",
        skip_tags: str = "",
        start_at_task: str = "",
        forks: int = 0,
        timeout: int = 0,
        become: bool = False,
        verbosity: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not playbook:
            return ToolResult.fail("workspace_path and playbook are required")

        from ansible_forge.tools.ee_runtime import is_ee_enabled

        if not is_ee_enabled():
            from ansible_forge.tools.python_resolver import resolve_or_install_python_async

            await resolve_or_install_python_async()

        ws = Path(workspace_path)
        pb_path = ws / playbook
        if pb_path.exists() and not is_ee_enabled():
            from ansible_forge.dep_manager import ensure_deps_for_playbook

            await ensure_deps_for_playbook(pb_path)
        if not (ws / playbook).exists():
            existing = sorted(
                str(p.relative_to(ws))
                for p in ws.rglob("*.y*ml")
                if p.suffix in (".yml", ".yaml")
                and not any(
                    part.startswith(".") or part == "__pycache__"
                    for part in p.relative_to(ws).parts
                )
                and p.stat().st_size < 1_000_000
            )[:20]
            hint = ""
            if existing:
                hint = "\n\nExisting playbook/YAML files in workspace:\n" + "\n".join(
                    f"  - {f}" for f in existing
                )
            return ToolResult.fail(
                f"Playbook not found: {ws / playbook}{hint}"
            )

        cmdline_args: list[str] = []
        if mode == "check":
            cmdline_args.extend(["--check", "--diff"])

        if limit:
            cmdline_args.extend(["--limit", limit])
        if tags:
            cmdline_args.extend(["--tags", tags])
        if skip_tags:
            cmdline_args.extend(["--skip-tags", skip_tags])
        if start_at_task:
            cmdline_args.extend(["--start-at-task", start_at_task])
        if forks and forks > 0:
            cmdline_args.extend(["--forks", str(forks)])
        if become:
            cmdline_args.append("--become")

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

        _inject_python_interpreter(ws, playbook, merged_vars)

        ensure_ansible_cfg(ws)
        (ws / ".tuyere").mkdir(parents=True, exist_ok=True)

        live_queue: asyncio.Queue[dict[str, Any]] | None = kwargs.pop("_live_log_queue", None)

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", merged_vars)

            envvars = _runner_envvars()
            for key, value in merged_vars.items():
                if key.isupper() or key.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                    envvars[key] = str(value)
            for key in vault_keys:
                upper = key.upper()
                if upper != key and upper not in envvars:
                    envvars[upper] = str(merged_vars[key])

            return await self._run_playbook(
                ws, run_dir, playbook, verbosity, envvars, live_queue,
                cmdline_args, merged_vars, inventory, mode, timeout, kwargs,
            )

    async def _run_playbook(
        self,
        ws: Path,
        run_dir: Path,
        playbook: str,
        verbosity: int,
        envvars: dict[str, str],
        live_queue: asyncio.Queue[dict[str, Any]] | None,
        cmdline_args: list[str],
        merged_vars: dict[str, Any],
        inventory: str,
        mode: str,
        timeout: int,
        kwargs: dict[str, Any],
    ) -> ToolResult:
        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(run_dir),
            "project_dir": str(ws),
            "playbook": playbook,
            "verbosity": verbosity,
            "envvars": envvars,
        }

        collected_events: list[dict[str, Any]] = []

        if live_queue is not None:
            import contextlib as _ctxlib

            loop_ref = asyncio.get_running_loop()

            def _on_event(event: dict[str, Any]) -> bool:
                ev_type = event.get("event", "")
                if ev_type in _CAPTURE_EVENT_TYPES:
                    collected_events.append(event)
                if ev_type in _LIVE_EVENT_TYPES:
                    formatted = _format_live_event(event)
                    if formatted:
                        with _ctxlib.suppress(Exception):
                            loop_ref.call_soon_threadsafe(live_queue.put_nowait, formatted)
                return True

            runner_kwargs["event_handler"] = _on_event
        if cmdline_args:
            runner_kwargs["cmdline"] = " ".join(cmdline_args)
        if merged_vars:
            runner_kwargs["extravars"] = merged_vars
        if inventory:
            inv_path = self._resolve_inventory(ws, inventory)
            if not inv_path.exists():
                _local_names = {"localhost", "localhost.yml", "localhost.yaml",
                                "local", "local.yml", "local.yaml"}
                if inventory.rsplit("/", 1)[-1] in _local_names:
                    from ansible_forge.tools.ee_runtime import is_ee_enabled

                    inv_path.parent.mkdir(parents=True, exist_ok=True)
                    inv_line = "localhost ansible_connection=local"
                    if not is_ee_enabled():
                        interp = _resolve_python_interpreter()
                        if interp and interp != "auto_silent":
                            inv_line += f" ansible_python_interpreter={interp}"
                    inv_path.write_text(f"[local]\n{inv_line}\n")
                    logger.info("auto_created_localhost_inventory", path=str(inv_path))
                else:
                    return ToolResult.fail(
                        f"Inventory not found: {inv_path}. "
                        f"Use manage_inventory to create it first."
                    )
            runner_kwargs["inventory"] = str(inv_path)
            missing = find_missing_secrets(inv_path, merged_vars)
            if missing:
                return ToolResult.fail(
                    f"Inventory references secrets not in the vault: {', '.join(missing)}. "
                    f"Use request_secret to collect them from the user before retrying."
                )

        effective_timeout = min(
            timeout if timeout and timeout > 0 else _DEFAULT_PLAYBOOK_TIMEOUT,
            _MAX_PLAYBOOK_TIMEOUT,
        )

        from ansible_forge.tools.ee_runtime import configure_ee_runner, is_remote_mode

        remote_path = is_remote_mode()
        extra_log_dirs: list[Path] = []
        log_snapshot: dict[str, float] = {}

        if remote_path:
            result = await self._run_playbook_in_container(
                ws, playbook, inventory, cmdline_args, merged_vars,
                envvars, verbosity, effective_timeout,
            )
            collected_events = []
        else:
            inv_for_stage = self._resolve_inventory(ws, inventory) if inventory else None
            await configure_ee_runner(
                ws, run_dir, runner_kwargs, inventory_path=inv_for_stage
            )

            extra_log_dirs = _extract_extra_log_dirs(ws, merged_vars, playbook)
            log_snapshot = _snapshot_log_files(ws, extra_dirs=extra_log_dirs)

            loop = asyncio.get_running_loop()
            thread, runner = await loop.run_in_executor(
                None,
                functools.partial(ansible_runner.run_async, **runner_kwargs),
            )

            log_watcher: asyncio.Task[None] | None = None
            if live_queue is not None:
                log_watcher = asyncio.create_task(
                    _tail_new_logs(ws, log_snapshot, live_queue, extra_dirs=extra_log_dirs)
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
                logger.info("playbook_cancelled", playbook=playbook)
                raise
            except TimeoutError:
                runner.cancel_callback = lambda: None
                runner.canceled = True
                _kill_runner(runner)
                await loop.run_in_executor(None, lambda: thread.join(timeout=10))
                mins = effective_timeout // 60
                return ToolResult.fail(
                    f"Playbook timed out after {mins} minute(s). "
                    f"Consider increasing the timeout parameter if the operation "
                    f"legitimately needs more time."
                )
            finally:
                if log_watcher and not log_watcher.done():
                    log_watcher.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await log_watcher
            result = runner

        raw_events = collected_events or get_runner_events(result)

        events = []
        for event in raw_events:
            ev_type = event.get("event", "")
            if ev_type in _CAPTURE_EVENT_TYPES:
                events.append({
                    "event": ev_type,
                    "host": event.get("event_data", {}).get("host", ""),
                    "task": event.get("event_data", {}).get("task", ""),
                    "result": _summarize_event_result(event.get("event_data", {}).get("res", {})),
                })

        _raw = read_runner_stdout(result)
        raw_stdout = _raw[-8000:] if len(_raw) > 8000 else _raw

        summary = {
            "status": result.status,
            "rc": result.rc,
            "stats": result.stats,
            "event_count": len(events),
        }

        detected_logs = (
            []
            if remote_path
            else _detect_new_log_files(ws, log_snapshot, extra_dirs=extra_log_dirs)
        )

        result_data = {
            "summary": summary,
            "events": events[:50],
            "mode": mode,
            "playbook": playbook,
            "raw_stdout": raw_stdout,
            "detected_logs": detected_logs,
        }

        if mode == "apply" and result.status == "successful":
            self._cache_gathered_facts(ws, result)

        if mode == "check":
            if result.status == "successful":
                return ToolResult(
                    status=ToolStatus.NEEDS_APPROVAL,
                    output=f"Preview completed — {len(events)} step(s) would run. No changes were made.",
                    data=result_data,
                )
            diag = diagnose_runner_failure(events, raw_stdout=raw_stdout, rc=result.rc)
            return ToolResult.fail(
                f"Preview failed ({playbook}). {diag}",
                **result_data,
            )

        if result.status == "successful":
            return ToolResult.ok(
                output=f"Deployment completed successfully ({len(events)} steps ran).",
                **result_data,
            )
        diag = diagnose_runner_failure(events, raw_stdout=raw_stdout, rc=result.rc)
        return ToolResult.fail(
            f"Deployment failed ({playbook}). {diag}",
            **result_data,
        )

    async def _run_playbook_in_container(
        self,
        ws: Path,
        playbook: str,
        inventory: str,
        cmdline_args: list[str],
        merged_vars: dict[str, Any],
        envvars: dict[str, str],
        verbosity: int,
        timeout: int,
    ) -> Any:
        """Run the playbook via ansible-playbook inside the EE container.

        Used in remote EE mode where ansible-runner process_isolation cannot
        bridge the local/remote filesystem split.
        """
        from ansible_forge.tools.container_runner import run_playbook_in_container

        inv_rel = ""
        if inventory:
            inv_p = self._resolve_inventory(ws, inventory)
            if inv_p.exists():
                try:
                    inv_rel = str(inv_p.relative_to(ws))
                except ValueError:
                    inv_rel = str(inv_p)
        return await run_playbook_in_container(
            ws=ws,
            playbook=playbook,
            inventory=inv_rel,
            cmdline_args=cmdline_args,
            extravars=merged_vars,
            envvars=envvars,
            verbosity=verbosity,
            timeout=timeout,
        )

    @staticmethod
    def _cache_gathered_facts(ws: Path, runner: Any) -> None:
        """Update .tuyere/artifacts/host_facts.json with facts from setup events."""
        import json as _json

        facts_path = ws / ".tuyere" / "artifacts" / "host_facts.json"
        existing: dict[str, Any] = {}
        if facts_path.exists():
            with contextlib.suppress(Exception):
                existing = _json.loads(facts_path.read_text(encoding="utf-8"))

        updated = False
        for event in get_runner_events(runner):
            if event.get("event") not in ("runner_on_ok", "runner_on_changed"):
                continue
            ev_data = event.get("event_data", {})
            res = ev_data.get("res", {})
            ansible_facts = res.get("ansible_facts", {})
            if not ansible_facts:
                continue
            host = ev_data.get("host", "")
            if not host:
                continue
            curated: dict[str, Any] = {}
            for key in ("ansible_os_family", "ansible_distribution",
                        "ansible_distribution_version", "ansible_architecture",
                        "ansible_hostname", "ansible_fqdn", "ansible_default_ipv4",
                        "ansible_memtotal_mb", "ansible_processor_vcpus",
                        "ansible_mounts", "ansible_pkg_mgr", "ansible_service_mgr",
                        "ansible_kernel"):
                if key in ansible_facts:
                    curated[key] = ansible_facts[key]
            if curated:
                existing[host] = curated
                updated = True

        if updated:
            facts_path.parent.mkdir(parents=True, exist_ok=True)
            facts_path.write_text(_json.dumps(existing, indent=2), encoding="utf-8")
            logger.info("host_facts_cached", path=str(facts_path), hosts=len(existing))



_RESULT_KEYS = (
    "changed", "msg", "stdout", "stderr", "diff", "rc",
    "skipped", "warnings", "module_stdout", "module_stderr",
    "exception", "reason",
)


def _summarize_event_result(res: Any) -> dict[str, Any]:
    """Extract key fields from a task result to keep event data manageable."""
    if not isinstance(res, dict):
        return {"msg": str(res)} if res else {}
    out = {k: res[k] for k in _RESULT_KEYS if k in res}
    if "results" in res and isinstance(res["results"], list):
        out["results"] = [
            {k: item[k] for k in _RESULT_KEYS if k in item}
            if isinstance(item, dict)
            else {"msg": str(item)}
            for item in res["results"][:20]
        ]
    return out
