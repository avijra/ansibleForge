"""Execute Ansible playbooks via ansible-runner with check-mode and apply support."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import os
import signal
import stat
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus
from ansible_forge.tools.secret_check import find_missing_secrets

logger = get_logger(__name__)

_DEFAULT_PLAYBOOK_TIMEOUT = 3600
_MAX_PLAYBOOK_TIMEOUT = 86400

_LIVE_EVENT_TYPES = frozenset({
    "playbook_on_play_start",
    "playbook_on_task_start",
    "runner_on_ok",
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

    if ev_type == "runner_on_ok":
        res = ev_data.get("res", {})
        return {
            "type": "task_ok",
            "host": ev_data.get("host", ""),
            "task": ev_data.get("task", ""),
            "changed": res.get("changed", False),
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


_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


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
            "tags, skip_tags, start_at_task, forks, timeout, and verbosity for full CLI "
            "parity. Set timeout based on expected duration — default is 1 hour, max 2 "
            "hours. Estimate timeout from task complexity and host count. "
            "Always prefer 'check' mode first."
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
    def _materialize_ssh_keys(ws: Path, merged_vars: dict[str, Any]) -> list[Path]:
        """Write SSH key secrets to disk so ansible-runner can use them.

        Scans ``merged_vars`` for values that look like SSH private keys
        (by variable name or content).  Each match is written to the
        workspace with ``0600`` permissions and the variable value is
        replaced with the file path so Ansible picks it up automatically.

        Returns the list of files created (for optional cleanup).
        """
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
            os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)  # 0600
            merged_vars[var_name] = str(key_file)
            files.append(key_file)
            logger.info(
                "ssh_key_materialized",
                variable=var_name,
                path=str(key_file),
            )
        return files

    @staticmethod
    def _clean_stale_env(ws: Path) -> None:
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
                path.unlink()

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

        ws = Path(workspace_path)
        if not (ws / playbook).exists():
            return ToolResult.fail(f"Playbook not found: {ws / playbook}")

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
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            merged_vars.update(vault.get_all())
        if extra_vars:
            merged_vars.update(extra_vars)

        self._materialize_ssh_keys(ws, merged_vars)
        self._clean_stale_env(ws)

        live_queue: asyncio.Queue[dict[str, Any]] | None = kwargs.pop("_live_log_queue", None)

        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(ws / ".tuyere"),
            "project_dir": str(ws),
            "playbook": playbook,
            "verbosity": verbosity,
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
        if cmdline_args:
            runner_kwargs["cmdline"] = " ".join(cmdline_args)
        if merged_vars:
            runner_kwargs["extravars"] = merged_vars
        if inventory:
            inv_path = self._resolve_inventory(ws, inventory)
            if inv_path.exists():
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

        log_snapshot = _snapshot_log_files(ws)

        loop = asyncio.get_event_loop()
        thread, runner = await loop.run_in_executor(
            None,
            functools.partial(ansible_runner.run_async, **runner_kwargs),
        )

        log_watcher: asyncio.Task[None] | None = None
        if live_queue is not None:
            log_watcher = asyncio.create_task(
                _tail_new_logs(ws, log_snapshot, live_queue)
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

        captured_events = (
            "runner_on_ok", "runner_on_failed", "runner_on_skipped",
            "runner_on_changed", "runner_on_unreachable",
        )
        events = []
        for event in result.events:
            if event.get("event") in captured_events:
                events.append({
                    "event": event["event"],
                    "host": event.get("event_data", {}).get("host", ""),
                    "task": event.get("event_data", {}).get("task", ""),
                    "result": _summarize_event_result(event.get("event_data", {}).get("res", {})),
                })

        raw_stdout = result.stdout.read() if hasattr(result.stdout, "read") else str(result.stdout)

        summary = {
            "status": result.status,
            "rc": result.rc,
            "stats": result.stats,
            "event_count": len(events),
        }

        detected_logs = _detect_new_log_files(ws, log_snapshot)

        result_data = {
            "summary": summary,
            "events": events[:50],
            "mode": mode,
            "playbook": playbook,
            "raw_stdout": raw_stdout,
            "detected_logs": detected_logs,
        }

        if mode == "check":
            if result.status == "successful":
                return ToolResult(
                    status=ToolStatus.NEEDS_APPROVAL,
                    output=f"Preview completed — {len(events)} step(s) would run. No changes were made.",
                    data=result_data,
                )
            return ToolResult.fail(
                "Preview failed — check the execution log below for details.",
                **result_data,
            )

        if result.status == "successful":
            return ToolResult.ok(
                output=f"Deployment completed successfully ({len(events)} steps ran).",
                **result_data,
            )
        return ToolResult.fail(
            "Deployment failed — check the execution log below for details.",
            **result_data,
        )


_LOG_EXTENSIONS = {".log", ".out"}
_LOG_MAX_PREVIEW = 2000
_LOG_MAX_FILES = 10


def _snapshot_log_files(ws: Path) -> dict[str, float]:
    snapshot: dict[str, float] = {}
    try:
        for ext in _LOG_EXTENSIONS:
            for f in ws.rglob(f"*{ext}"):
                if ".tuyere" in f.parts or "node_modules" in f.parts:
                    continue
                with contextlib.suppress(OSError):
                    snapshot[str(f.relative_to(ws))] = f.stat().st_mtime
    except Exception:
        pass
    return snapshot


_LOG_MAX_READ = 64 * 1024


def _tail_text(path: Path, max_chars: int) -> str:
    size = path.stat().st_size
    read_bytes = min(size, max_chars * 4)
    with path.open("rb") as fh:
        if size > read_bytes:
            fh.seek(size - read_bytes)
        raw = fh.read(read_bytes)
    text = raw.decode("utf-8", errors="replace")
    return text[-max_chars:] if len(text) > max_chars else text


def _detect_new_log_files(
    ws: Path, before: dict[str, float]
) -> list[dict[str, str]]:
    detected: list[dict[str, str]] = []
    try:
        for ext in _LOG_EXTENSIONS:
            for f in ws.rglob(f"*{ext}"):
                if ".tuyere" in f.parts or "node_modules" in f.parts:
                    continue
                try:
                    real = f.resolve(strict=True)
                    ws_real = ws.resolve()
                    if not str(real).startswith(str(ws_real) + os.sep) and real != ws_real:
                        continue
                    rel = str(f.relative_to(ws))
                    mtime = real.stat().st_mtime
                    fsize = real.stat().st_size
                    if fsize > _LOG_MAX_READ:
                        continue
                    if rel not in before or mtime > before[rel]:
                        preview = _tail_text(real, _LOG_MAX_PREVIEW)
                        detected.append({
                            "path": rel,
                            "size": str(fsize),
                            "preview": preview,
                        })
                except OSError:
                    pass
    except Exception:
        pass
    return detected[:_LOG_MAX_FILES]


_TAIL_POLL_INTERVAL = 3.0
_TAIL_MAX_LINE_LEN = 500


async def _tail_new_logs(
    ws: Path, baseline: dict[str, float], queue: asyncio.Queue[dict[str, Any]]
) -> None:
    positions: dict[str, int] = {}
    ws_resolved = ws.resolve()

    while True:
        await asyncio.sleep(_TAIL_POLL_INTERVAL)
        try:
            for ext in _LOG_EXTENSIONS:
                for f in ws.rglob(f"*{ext}"):
                    if ".tuyere" in f.parts or "node_modules" in f.parts:
                        continue
                    try:
                        real = f.resolve(strict=True)
                        if not str(real).startswith(str(ws_resolved) + os.sep) and real != ws_resolved:
                            continue
                        rel = str(f.relative_to(ws))
                        stat_info = real.stat()
                        if stat_info.st_size > _LOG_MAX_READ:
                            continue
                        old_mtime = baseline.get(rel, 0)
                        if stat_info.st_mtime <= old_mtime and rel not in positions:
                            continue

                        pos = positions.get(rel, 0)
                        if stat_info.st_size <= pos:
                            continue

                        with real.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            new_data = fh.read(8192)
                            positions[rel] = fh.tell()

                        if new_data.strip():
                            lines = new_data.strip().splitlines()
                            preview = "\n".join(
                                ln[:_TAIL_MAX_LINE_LEN] for ln in lines[-10:]
                            )
                            with contextlib.suppress(Exception):
                                queue.put_nowait({
                                    "source": "log_file",
                                    "file": rel,
                                    "content": preview,
                                })
                    except OSError:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception:
            pass


_RESULT_KEYS = (
    "changed", "msg", "stdout", "stderr", "diff", "rc",
    "skipped", "warnings", "module_stdout", "module_stderr",
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
