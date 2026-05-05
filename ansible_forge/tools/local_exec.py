"""Local command execution tool — fallback shell on the host.

Commands are checked against a BLOCKED list (destructive operations like
rm -rf /, mkfs, dd) and a REDIRECT list (Ansible/Terraform CLIs that have
dedicated tools in the app).  Everything else is allowed through — the
system prompt guides the agent to prefer Ansible modules and Terraform, but
when those tools fail, local_exec is the safety net that prevents deadlock.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-[^\s]*r[^\s]*\s+/\s*$"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+.*of=/dev/"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\b:(){ :\|:& };:"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b|\bpoweroff\b|\bhalt\b"),
    re.compile(r"\bvi\b|\bvim\b|\bnano\b|\bed\b"),
]

_VERSION_RE = re.compile(r"^\s*\S+\s+(?:--?version|-V|version)\s*$")

_APP_TOOL_REDIRECT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bansible-galaxy\b"), "manage_galaxy tool (not local_exec)"),
    (re.compile(r"\bansible-playbook\b"), "execute_playbook tool (not local_exec)"),
    (re.compile(r"\bansible\s+(?!--version)"), "run_adhoc tool (not local_exec)"),
]

_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

MAX_OUTPUT_BYTES = 256_000
DEFAULT_TIMEOUT = 120


class LocalExec(BaseTool):
    @property
    def name(self) -> str:
        return "local_exec"

    @property
    def description(self) -> str:
        return (
            "Run a shell command on the local machine. Prefer Ansible modules "
            "(run_adhoc / execute_playbook) and terraform_exec when they work, "
            "but use this tool as fallback when those fail or for CLI tools "
            "like aws, kubectl, openshift-install, oc, helm, etc."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional working directory. Defaults to the session workspace.",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds. Default {DEFAULT_TIMEOUT}.",
                },
            },
            "required": ["command"],
        }

    @staticmethod
    def _check_segment(segment: str) -> str | None:
        stripped = segment.strip()
        if not stripped:
            return None

        if _VERSION_RE.match(stripped):
            return None

        for pattern, redirect in _APP_TOOL_REDIRECT:
            if pattern.search(stripped):
                return redirect

        return None

    @staticmethod
    def _check_command(command: str) -> str | None:
        segments = _SPLIT_RE.split(command)
        for seg in segments:
            result = LocalExec._check_segment(seg)
            if result is not None:
                return result
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.fail("No command provided.")

        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                return ToolResult.fail(
                    "Command blocked by safety filter: matches dangerous pattern."
                )

        rejection = self._check_command(command)
        if rejection:
            logger.warning(
                "local_exec_blocked",
                command=command[:200],
                reason=rejection[:200],
            )
            return ToolResult.fail(
                f"BLOCKED: {rejection}. "
                f"Use the dedicated tool instead of local_exec for this."
            )

        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 600)
        cwd = kwargs.get("working_directory") or kwargs.get("_workspace_path")

        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"

        logger.info("local_exec_start", command=command[:200], cwd=cwd, timeout=timeout)

        proc = None
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.CancelledError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.debug("cancel_kill_failed", exc_info=True)
            logger.info("local_exec_cancelled", command=command[:200])
            raise
        except TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.debug("timeout_kill_failed", exc_info=True)
            return ToolResult.fail(f"Command timed out after {timeout}s: {command[:100]}")
        except FileNotFoundError:
            return ToolResult.fail(f"Working directory not found: {cwd}")
        except Exception as exc:
            return ToolResult.fail(f"Failed to execute: {exc}")

        stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        exit_code = proc.returncode or 0

        logger.info(
            "local_exec_done",
            command=command[:200],
            exit_code=exit_code,
            stdout_len=len(stdout),
            stderr_len=len(stderr),
        )

        if exit_code != 0:
            combined = stdout
            if stderr:
                combined = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else stderr
            return ToolResult.fail(
                f"Exit code {exit_code}",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                combined_output=combined,
            )

        return ToolResult.ok(
            output=stdout or "(no output)",
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
