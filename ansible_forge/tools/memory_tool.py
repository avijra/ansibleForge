from __future__ import annotations

from typing import Any

from ansible_forge.tools.base import BaseTool, ToolResult


class MemoryTool(BaseTool):
    @property
    def name(self) -> str:
        return "memory"

    @property
    def description(self) -> str:
        return (
            "Manage persistent workspace memory (MEMORY.md). "
            "Use this to store environment facts, SSH quirks, conventions, "
            "lessons learned, and milestones that should persist across sessions. "
            "Memory is bounded to 3,000 characters — curate it carefully."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["add", "replace", "remove", "read", "clear"],
                    "description": (
                        "add: append a new entry. "
                        "replace: swap old_text with new_text. "
                        "remove: delete lines matching pattern. "
                        "read: show current memory contents. "
                        "clear: wipe all memory."
                    ),
                },
                "entry": {
                    "type": "string",
                    "description": "Text to add (for 'add' action).",
                },
                "old_text": {
                    "type": "string",
                    "description": "Existing text to replace (for 'replace' action).",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text (for 'replace' action).",
                },
                "pattern": {
                    "type": "string",
                    "description": "Substring to match for line removal (for 'remove' action).",
                },
            },
            "required": ["action"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ansible_forge.knowledge.workspace_memory import WorkspaceMemory

        action = kwargs.get("action", "read")
        workspace_path = kwargs.get("workspace_path", "")
        workspace_id = workspace_path.replace("/", "_").replace("\\", "_").strip("_") or "default"
        mem = WorkspaceMemory(workspace_id)

        if action == "read":
            content = mem.read()
            if not content.strip():
                return ToolResult.ok("Workspace memory is empty.")
            return ToolResult.ok(content)

        if action == "add":
            entry = kwargs.get("entry", "")
            if not entry:
                return ToolResult.fail("'entry' is required for the 'add' action.")
            result = mem.add(entry)
            return ToolResult.ok(result)

        if action == "replace":
            old_text = kwargs.get("old_text", "")
            new_text = kwargs.get("new_text", "")
            if not old_text:
                return ToolResult.fail("'old_text' is required for the 'replace' action.")
            result = mem.replace(old_text, new_text)
            return ToolResult.ok(result)

        if action == "remove":
            pattern = kwargs.get("pattern", "")
            if not pattern:
                return ToolResult.fail("'pattern' is required for the 'remove' action.")
            result = mem.remove(pattern)
            return ToolResult.ok(result)

        if action == "clear":
            result = mem.clear()
            return ToolResult.ok(result)

        return ToolResult.fail(f"Unknown action: {action}")
