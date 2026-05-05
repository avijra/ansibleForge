"""Write arbitrary files to the workspace — templates, configs, variable files, etc."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class FileWriter(BaseTool):
    """Write any file to the workspace without YAML validation.

    Use this for Jinja2 templates (.j2), configuration files, variable files,
    scripts, or any non-playbook content that the playbook generator would reject.
    """

    @property
    def name(self) -> str:
        return "write_file"

    @property
    def description(self) -> str:
        return (
            "Write any file to the workspace directory. Use this for Jinja2 templates (.j2), "
            "configuration files, shell scripts, variable files, or any content that is NOT "
            "an Ansible playbook. Unlike generate_playbook, this tool does NOT validate YAML "
            "structure, so it can write Jinja2 templates with {{ variables }}, raw config files, "
            "INI files, shell scripts, etc. "
            "The file is written relative to the project directory."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": (
                        "Relative path for the file within the workspace project directory. "
                        "Examples: 'templates/nginx.conf.j2', "
                        "'roles/myrole/templates/install-config.yaml.j2', "
                        "'roles/myrole/defaults/main.yml', 'scripts/setup.sh'"
                    ),
                },
                "content": {
                    "type": "string",
                    "description": "Full file content to write",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
            },
            "required": ["file_path", "content", "workspace_path"],
        }

    async def execute(
        self,
        file_path: str = "",
        content: str = "",
        workspace_path: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not file_path or content is None or not workspace_path:
            return ToolResult.fail("file_path, content, and workspace_path are required")

        project_dir = Path(workspace_path).resolve()
        target = (project_dir / file_path).resolve()
        if not target.is_relative_to(project_dir):
            return ToolResult.fail(
                f"Path escapes workspace: {file_path!r} resolves outside project directory"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

        logger.info("file_written", path=str(target), size=len(content))

        return ToolResult.ok(
            output=f"File written to {target}",
            path=str(target),
            size=len(content),
        )
