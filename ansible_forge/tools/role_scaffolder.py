"""Scaffold Ansible roles following Galaxy best practices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible_forge.tools.base import BaseTool, ToolResult

ROLE_DIRS = [
    "defaults",
    "files",
    "handlers",
    "meta",
    "tasks",
    "templates",
    "vars",
]

DEFAULT_META = """\
---
galaxy_info:
  author: Tuyere
  role_name: "{role_name}"
  namespace: tuyere
  description: "{description}"
  license: MIT
  min_ansible_version: "2.17"
  platforms: {platforms}
  galaxy_tags: []
dependencies: []
"""

DEFAULT_MOLECULE_YML = """\
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: "{role_name}-test"
    image: "geerlingguy/docker-ubuntu2404-ansible:latest"
    pre_build_image: true
    command: ""
    volumes:
      - /sys/fs/cgroup:/sys/fs/cgroup:rw
    cgroupns_mode: host
    privileged: true
provisioner:
  name: ansible
verifier:
  name: ansible
"""

DEFAULT_CONVERGE_YML = """\
---
- name: Converge
  hosts: all
  roles:
    - role: {role_name}
"""

DEFAULT_VERIFY_YML = """\
---
- name: Verify
  hosts: all
  gather_facts: false
  tasks:
    - name: Placeholder verification
      ansible.builtin.assert:
        that: true
"""

DEFAULT_TASKS_MAIN = """\
---
# Tasks for {role_name}
"""

DEFAULT_HANDLERS_MAIN = """\
---
# Handlers for {role_name}
"""

DEFAULT_DEFAULTS_MAIN = """\
---
# Default variables for {role_name}
"""


class RoleScaffolder(BaseTool):
    @property
    def name(self) -> str:
        return "scaffold_role"

    @property
    def description(self) -> str:
        return (
            "Create an Ansible role — the PRIMARY unit of automation. Call this BEFORE "
            "generate_playbook. Every logical component (nginx, gpu_operator, k8s_setup) "
            "gets its own role. Populate tasks_content, defaults_content, handlers_content, "
            "and templates in a SINGLE call. Playbooks are thin wrappers that import roles."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "role_name": {
                    "type": "string",
                    "description": "Name of the role (e.g. 'nginx', 'common')",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace project directory",
                },
                "tasks_content": {
                    "type": "string",
                    "description": "YAML content for tasks/main.yml (optional)",
                },
                "defaults_content": {
                    "type": "string",
                    "description": "YAML content for defaults/main.yml (optional)",
                },
                "handlers_content": {
                    "type": "string",
                    "description": "YAML content for handlers/main.yml (optional)",
                },
                "meta_description": {
                    "type": "string",
                    "description": "Short description for meta/main.yml (optional)",
                },
                "templates": {
                    "type": "object",
                    "description": "Map of template filename -> content to write into templates/ (optional)",
                    "additionalProperties": {"type": "string"},
                },
                "platforms": {
                    "type": "array",
                    "description": "List of target OS families for meta/main.yml (e.g. ['Ubuntu', 'EL', 'Debian'])",
                    "items": {"type": "string"},
                },
                "molecule": {
                    "type": "boolean",
                    "description": "Generate a default Molecule test scenario (default: true)",
                },
            },
            "required": ["role_name", "workspace_path"],
        }

    async def execute(
        self,
        role_name: str = "",
        workspace_path: str = "",
        tasks_content: str = "",
        defaults_content: str = "",
        handlers_content: str = "",
        meta_description: str = "",
        templates: dict[str, str] | None = None,
        platforms: list[str] | None = None,
        molecule: bool = True,
        **kwargs: Any,
    ) -> ToolResult:
        if not role_name or not workspace_path:
            return ToolResult.fail("role_name and workspace_path are required")

        ws_root = Path(workspace_path).resolve()
        roles_dir = (Path(workspace_path) / "roles" / role_name).resolve()
        if not roles_dir.is_relative_to(ws_root):
            return ToolResult.fail(f"Role name escapes workspace: {role_name}")
        created_dirs: list[str] = []

        for d in ROLE_DIRS:
            subdir = roles_dir / d
            subdir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(subdir))

        platforms_yaml = "[]"
        if platforms:
            entries = "\n".join(f"    - name: {p}" for p in platforms)
            platforms_yaml = f"\n{entries}"

        (roles_dir / "tasks" / "main.yml").write_text(
            tasks_content or DEFAULT_TASKS_MAIN.format(role_name=role_name), encoding="utf-8"
        )
        (roles_dir / "defaults" / "main.yml").write_text(
            defaults_content or DEFAULT_DEFAULTS_MAIN.format(role_name=role_name), encoding="utf-8"
        )
        (roles_dir / "handlers" / "main.yml").write_text(
            handlers_content or DEFAULT_HANDLERS_MAIN.format(role_name=role_name), encoding="utf-8"
        )
        (roles_dir / "meta" / "main.yml").write_text(
            DEFAULT_META.format(
                role_name=role_name,
                description=meta_description or role_name,
                platforms=platforms_yaml,
            ),
            encoding="utf-8",
        )
        (roles_dir / "vars" / "main.yml").write_text(
            f"---\n# Internal variables for {role_name} (not user-facing)\n",
            encoding="utf-8",
        )

        if templates:
            for tpl_name, tpl_content in templates.items():
                (roles_dir / "templates" / tpl_name).write_text(tpl_content, encoding="utf-8")

        if molecule:
            mol_dir = roles_dir / "molecule" / "default"
            mol_dir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(mol_dir))
            (mol_dir / "molecule.yml").write_text(
                DEFAULT_MOLECULE_YML.format(role_name=role_name), encoding="utf-8"
            )
            (mol_dir / "converge.yml").write_text(
                DEFAULT_CONVERGE_YML.format(role_name=role_name), encoding="utf-8"
            )
            (mol_dir / "verify.yml").write_text(
                DEFAULT_VERIFY_YML.format(role_name=role_name), encoding="utf-8"
            )

        return ToolResult.ok(
            output=f"Role '{role_name}' scaffolded at {roles_dir}",
            path=str(roles_dir),
            directories=created_dirs,
        )
