"""Scaffold and run Molecule test scenarios for Ansible roles."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

DEFAULT_MOLECULE_YML = """\
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: "{image}"
    pre_build_image: true
provisioner:
  name: ansible
verifier:
  name: ansible
"""

DEFAULT_CONVERGE = """\
---
- name: Converge
  hosts: all
  roles:
    - role: {role_name}
"""

DEFAULT_VERIFY = """\
---
- name: Verify
  hosts: all
  gather_facts: false
  tasks:
    - name: Placeholder verification
      ansible.builtin.assert:
        that: true
"""


class MoleculeRunner(BaseTool):
    @property
    def name(self) -> str:
        return "run_molecule"

    @property
    def description(self) -> str:
        return (
            "Scaffold Molecule test scenarios for an Ansible role or run existing scenarios. "
            "Uses the Docker driver. Actions: 'init' to scaffold, 'test' to run full test, "
            "'converge' to only apply, 'verify' to only verify, 'destroy' to tear down."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["init", "test", "converge", "verify", "destroy"],
                    "description": "Molecule action to perform",
                },
                "role_path": {
                    "type": "string",
                    "description": "Absolute path to the role directory",
                },
                "scenario_name": {
                    "type": "string",
                    "description": "Scenario name (default: 'default')",
                },
                "image": {
                    "type": "string",
                    "description": "Docker image for the test instance (default: ubuntu:22.04)",
                },
            },
            "required": ["action", "role_path"],
        }

    async def execute(
        self,
        action: str = "",
        role_path: str = "",
        scenario_name: str = "default",
        image: str = "ubuntu:22.04",
        **kwargs: Any,
    ) -> ToolResult:
        if not action or not role_path:
            return ToolResult.fail("action and role_path are required")

        role = Path(role_path)
        if not role.is_dir():
            return ToolResult.fail(f"Role directory not found: {role_path}")

        if action == "init":
            return self._scaffold(role, scenario_name, image)

        return await self._run_molecule(action, role, scenario_name)

    @staticmethod
    def _scaffold(role: Path, scenario: str, image: str) -> ToolResult:
        role_name = role.name
        mol_dir = role / "molecule" / scenario
        mol_dir.mkdir(parents=True, exist_ok=True)

        (mol_dir / "molecule.yml").write_text(
            DEFAULT_MOLECULE_YML.format(image=image), encoding="utf-8"
        )
        (mol_dir / "converge.yml").write_text(
            DEFAULT_CONVERGE.format(role_name=role_name), encoding="utf-8"
        )
        (mol_dir / "verify.yml").write_text(DEFAULT_VERIFY, encoding="utf-8")

        return ToolResult.ok(
            output=f"Molecule scenario '{scenario}' scaffolded at {mol_dir}",
            path=str(mol_dir),
        )

    @staticmethod
    async def _run_molecule(action: str, role: Path, scenario: str) -> ToolResult:
        proc = await asyncio.create_subprocess_exec(
            "molecule",
            action,
            "-s",
            scenario,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(role),
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=600)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return ToolResult.fail(f"Molecule {action} timed out after 10 minutes.")
        stdout = stdout_b.decode(errors="replace")
        stderr = stderr_b.decode(errors="replace")

        combined = stdout + ("\n" + stderr if stderr else "")

        if proc.returncode != 0:
            return ToolResult.fail(
                f"Molecule {action} failed (exit {proc.returncode}):\n{combined}"
            )

        return ToolResult.ok(
            output=f"Molecule {action} succeeded:\n{combined}",
            exit_code=proc.returncode,
        )
