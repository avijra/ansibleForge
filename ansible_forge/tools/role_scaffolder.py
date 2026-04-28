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
  author: AnsibleForge
  description: "{description}"
  license: MIT
  min_ansible_version: "2.17"
  platforms: []
  galaxy_tags: []
dependencies: []
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
            "Create an Ansible role directory structure following Galaxy best practices. "
            "Optionally populate tasks/main.yml, defaults/main.yml, handlers/main.yml, "
            "and meta/main.yml with provided content."
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
        **kwargs: Any,
    ) -> ToolResult:
        if not role_name or not workspace_path:
            return ToolResult.fail("role_name and workspace_path are required")

        roles_dir = Path(workspace_path) / "project" / "roles" / role_name
        created_dirs: list[str] = []

        for d in ROLE_DIRS:
            subdir = roles_dir / d
            subdir.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(subdir))

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
            DEFAULT_META.format(description=meta_description or role_name), encoding="utf-8"
        )

        if templates:
            for tpl_name, tpl_content in templates.items():
                (roles_dir / "templates" / tpl_name).write_text(tpl_content, encoding="utf-8")

        return ToolResult.ok(
            output=f"Role '{role_name}' scaffolded at {roles_dir}",
            path=str(roles_dir),
            directories=created_dirs,
        )
