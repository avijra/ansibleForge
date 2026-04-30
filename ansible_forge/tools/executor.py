"""Execute Ansible playbooks via ansible-runner with check-mode and apply support."""

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
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus

logger = get_logger(__name__)

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
            "and 'apply' (actually execute changes on target hosts). "
            "Always prefer 'check' mode first so the user can review before applying."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the ansible-runner workspace directory",
                },
                "playbook": {
                    "type": "string",
                    "description": "Playbook filename (relative to workspace/project/)",
                },
                "mode": {
                    "type": "string",
                    "enum": ["check", "apply"],
                    "description": "Execution mode: 'check' for dry-run, 'apply' for live execution",
                },
                "inventory": {
                    "type": "string",
                    "description": "Path to inventory file (relative to workspace/inventory/)",
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
        keys_dir = ws / "ssh_keys"
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
        env_dir = ws / "env"
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
        verbosity: int = 0,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not playbook:
            return ToolResult.fail("workspace_path and playbook are required")

        ws = Path(workspace_path)
        if not (ws / "project" / playbook).exists():
            return ToolResult.fail(f"Playbook not found: {ws / 'project' / playbook}")

        cmdline_args: list[str] = []
        if mode == "check":
            cmdline_args.extend(["--check", "--diff"])

        if limit:
            cmdline_args.extend(["--limit", limit])
        if tags:
            cmdline_args.extend(["--tags", tags])

        merged_vars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            merged_vars.update(vault.get_all())
        if extra_vars:
            merged_vars.update(extra_vars)

        self._materialize_ssh_keys(ws, merged_vars)
        self._clean_stale_env(ws)

        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(ws),
            "playbook": playbook,
            "verbosity": verbosity,
        }
        if cmdline_args:
            runner_kwargs["cmdline"] = " ".join(cmdline_args)
        if merged_vars:
            runner_kwargs["extravars"] = merged_vars
        if inventory:
            inv_path = self._resolve_inventory(ws, inventory)
            if inv_path.exists():
                runner_kwargs["inventory"] = str(inv_path)

        loop = asyncio.get_event_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, functools.partial(ansible_runner.run, **runner_kwargs)
                ),
                timeout=300,
            )
        except TimeoutError:
            return ToolResult.fail(
                "Playbook execution timed out after 5 minutes. "
                "Check host connectivity and SSH configuration."
            )

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

        result_data = {
            "summary": summary,
            "events": events[:50],
            "mode": mode,
            "playbook": playbook,
            "raw_stdout": raw_stdout,
        }

        if mode == "check":
            if result.status == "successful":
                return ToolResult(
                    status=ToolStatus.NEEDS_APPROVAL,
                    output=f"Dry-run completed successfully. {len(events)} task event(s).",
                    data=result_data,
                )
            return ToolResult.fail(
                f"Dry-run failed (status={result.status}, rc={result.rc})",
                **result_data,
            )

        if result.status == "successful":
            return ToolResult.ok(
                output=f"Playbook executed successfully. {len(events)} task event(s).",
                **result_data,
            )
        return ToolResult.fail(
            f"Playbook execution failed (status={result.status}, rc={result.rc})",
            **result_data,
        )


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
