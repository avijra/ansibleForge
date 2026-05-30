"""Generate Ansible playbooks from natural-language intent."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ansible_forge.tools.base import BaseTool, ToolResult


class PlaybookGenerator(BaseTool):
    """Generates well-structured YAML playbooks.

    The LLM produces the playbook content; this tool validates the YAML
    structure, writes it to the workspace, and returns the path.
    """

    @property
    def name(self) -> str:
        return "generate_playbook"

    @property
    def description(self) -> str:
        return (
            "Generate an Ansible playbook YAML file from a structured specification. "
            "Provide the playbook content as a YAML string with proper plays, tasks, "
            "FQCN module names, handlers, and idempotent patterns. "
            "The tool validates the YAML and writes it to the workspace."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook_name": {
                    "type": "string",
                    "description": "Relative path for the playbook within the workspace. Always use the playbooks/ prefix (e.g. 'playbooks/deploy_nginx.yml', 'playbooks/site.yml')",
                },
                "content": {
                    "type": "string",
                    "description": "Full playbook content as valid YAML",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace project directory",
                },
            },
            "required": ["playbook_name", "content", "workspace_path"],
        }

    async def execute(
        self,
        playbook_name: str = "",
        content: str = "",
        workspace_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not playbook_name or not content or not workspace_path:
            return ToolResult.fail("playbook_name, content, and workspace_path are required")

        if not playbook_name.endswith((".yml", ".yaml")):
            playbook_name += ".yml"

        try:
            parsed = yaml.safe_load(content)
        except yaml.YAMLError as exc:
            return ToolResult.fail(f"Invalid YAML: {exc}")

        if not isinstance(parsed, list):
            return ToolResult.fail("Playbook must be a YAML list of plays")

        project_dir = Path(workspace_path)
        project_dir.mkdir(parents=True, exist_ok=True)

        playbook_path = (project_dir / playbook_name).resolve()
        if not playbook_path.is_relative_to(project_dir.resolve()):
            return ToolResult.fail(f"Path escapes workspace: {playbook_name}")
        playbook_path.parent.mkdir(parents=True, exist_ok=True)
        playbook_path.write_text(content, encoding="utf-8")

        return ToolResult.ok(
            output=f"Playbook written to {playbook_path}",
            path=str(playbook_path),
            plays=len(parsed),
        )
