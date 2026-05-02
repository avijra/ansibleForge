"""Local command execution tool — runs arbitrary shell commands on the host."""

from __future__ import annotations

import asyncio
import os
import re
import shlex
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
]

MAX_OUTPUT_BYTES = 256_000
DEFAULT_TIMEOUT = 120


class LocalExec(BaseTool):
    @property
    def name(self) -> str:
        return "local_exec"

    @property
    def description(self) -> str:
        return (
            "Run a shell command on the local machine (the host running Tuyere). "
            "Use this for managing local infrastructure tools like tart, docker, "
            "vagrant, kubectl, brew, pip, or any CLI installed on the host. "
            "Also useful for diagnostics: checking processes, network, disk, etc."
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

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.fail("No command provided.")

        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                return ToolResult.fail(
                    f"Command blocked by safety filter: matches dangerous pattern."
                )

        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 600)
        cwd = kwargs.get("working_directory") or kwargs.get("_workspace_path")

        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"

        logger.info("local_exec_start", command=command[:200], cwd=cwd, timeout=timeout)

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
        except asyncio.TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
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
