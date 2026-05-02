"""Rollback planning tool — generates best-effort undo playbooks."""

from __future__ import annotations

from typing import Any

from ansible_forge.safety.rollback import RollbackPlanner
from ansible_forge.tools.base import BaseTool, ToolResult


class RollbackTool(BaseTool):

    def __init__(self) -> None:
        self._planner = RollbackPlanner()

    @property
    def name(self) -> str:
        return "generate_rollback"

    @property
    def description(self) -> str:
        return (
            "Analyze an existing playbook and generate a best-effort rollback playbook "
            "that reverses its changes. Use after a failed deployment or when the user "
            "wants an undo plan. The rollback playbook is written to the workspace and "
            "can be reviewed before execution."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "playbook": {
                    "type": "string",
                    "description": "Playbook filename (relative to project directory) to generate rollback for",
                },
            },
            "required": ["workspace_path", "playbook"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        playbook: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not playbook:
            return ToolResult.fail("workspace_path and playbook are required")
        return self._planner.generate(workspace_path, playbook)
