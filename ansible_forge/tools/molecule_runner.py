"""Molecule role testing tool — validates Ansible roles in isolated containers."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_VALID_ACTIONS = frozenset({"test", "create", "converge", "verify", "destroy", "lint"})


class MoleculeRunner(BaseTool):
    @property
    def name(self) -> str:
        return "run_molecule"

    @property
    def description(self) -> str:
        return (
            "Run Molecule tests on an Ansible role. Molecule provisions an isolated "
            "environment (Docker container), applies the role, and verifies the result. "
            "Use 'test' for the full create→converge→verify→destroy cycle, or individual "
            "actions for incremental development. Requires Docker to be running."
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
                "role_name": {
                    "type": "string",
                    "description": "Name of the role under roles/ to test",
                },
                "action": {
                    "type": "string",
                    "enum": sorted(_VALID_ACTIONS),
                    "description": (
                        "Molecule action: 'test' (full cycle), 'create' (provision), "
                        "'converge' (apply role), 'verify' (run checks), "
                        "'destroy' (teardown), 'lint' (static analysis)"
                    ),
                },
                "scenario": {
                    "type": "string",
                    "description": "Molecule scenario name (default: 'default')",
                },
            },
            "required": ["workspace_path", "role_name", "action"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        role_name: str = "",
        action: str = "test",
        scenario: str = "default",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not role_name:
            return ToolResult.fail("workspace_path and role_name are required")

        if action not in _VALID_ACTIONS:
            return ToolResult.fail(f"Invalid action: {action}. Must be one of: {', '.join(sorted(_VALID_ACTIONS))}")

        role_dir = Path(workspace_path) / "roles" / role_name
        if not role_dir.is_dir():
            return ToolResult.fail(f"Role directory not found: {role_dir}")

        molecule_dir = role_dir / "molecule" / scenario
        if not molecule_dir.is_dir():
            return ToolResult.fail(
                f"Molecule scenario '{scenario}' not found at {molecule_dir}. "
                f"Use scaffold_role to create one, or create molecule/{scenario}/molecule.yml manually."
            )

        from ansible_forge.tools.ee_runtime import is_ee_enabled, is_remote_mode

        cmd = ["molecule", action, "--scenario-name", scenario]
        logger.info("molecule_run", role=role_name, action=action, scenario=scenario)

        if is_ee_enabled():
            return await self._run_in_ee(
                cmd, role_dir, workspace_path, role_name, action, scenario,
                is_remote=is_remote_mode(),
            )

        if not shutil.which("docker") and not shutil.which("podman"):
            return ToolResult.fail(
                "Docker (or Podman) is required for Molecule but was not found. "
                "Install Docker Desktop and ensure it is running."
            )

        if not shutil.which("molecule"):
            return ToolResult.fail(
                "Molecule CLI not found. Install it: pip install 'molecule[docker]' "
                "or 'pip install molecule molecule-plugins[docker]'."
            )

        live_queue: asyncio.Queue[dict[str, Any]] | None = kwargs.pop("_live_log_queue", None)

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(role_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )

            lines: list[str] = []
            assert proc.stdout is not None
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    break
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                lines.append(line)
                if live_queue is not None:
                    await live_queue.put({"stream": "stdout", "line": line})

            await proc.wait()
            output = "\n".join(lines[-200:])

            if proc.returncode == 0:
                return ToolResult.ok(
                    output=f"Molecule {action} succeeded for role '{role_name}' (scenario: {scenario}).\n\n{output}",
                    role=role_name,
                    action=action,
                    scenario=scenario,
                )
            return ToolResult.fail(
                f"Molecule {action} failed for role '{role_name}' (exit code {proc.returncode}).\n\n{output}"
            )
        except asyncio.CancelledError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            raise
        except TimeoutError:
            return ToolResult.fail(f"Molecule {action} timed out for role '{role_name}'.")
        except Exception as exc:
            logger.error("molecule_error", role=role_name, error=str(exc), exc_info=True)
            return ToolResult.fail(f"Molecule {action} error: {exc}")

    async def _run_in_ee(
        self,
        cmd: list[str],
        role_dir: Path,
        workspace_path: str,
        role_name: str,
        action: str,
        scenario: str,
        is_remote: bool,
    ) -> ToolResult:
        """Run Molecule inside the EE container.

        Molecule provisions sibling Docker containers via the daemon socket, so
        the host socket is bind-mounted into the EE container. Remote EE mode is
        unsupported because the socket lives on the local host only.
        """
        if is_remote:
            return ToolResult.fail(
                "Molecule testing is not supported with a remote Execution "
                "Environment. Switch the EE to local mode (or run Molecule on a "
                "host with Docker) to test roles."
            )

        from ansible_forge.tools.ee_runtime import ee_exec

        socket = Path("/var/run/docker.sock")
        if not socket.exists():
            return ToolResult.fail(
                "Molecule needs the Docker daemon socket at /var/run/docker.sock, "
                "but it was not found. Ensure Docker is running locally."
            )

        rc, stdout, stderr = await ee_exec(
            cmd,
            cwd=role_dir,
            ws=Path(workspace_path),
            timeout=3600,
            extra_run_args=["-v", f"{socket}:{socket}"],
        )
        output = (stdout + ("\n" + stderr if stderr else ""))[-8000:]
        if rc == 0:
            return ToolResult.ok(
                output=f"Molecule {action} succeeded for role '{role_name}' (scenario: {scenario}).\n\n{output}",
                role=role_name,
                action=action,
                scenario=scenario,
            )
        return ToolResult.fail(
            f"Molecule {action} failed for role '{role_name}' (exit code {rc}).\n\n{output}"
        )
