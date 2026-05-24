"""Tests for the ToolRegistry."""

from __future__ import annotations

from typing import Any

import pytest

from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.registry import ToolRegistry, create_default_registry


class DummyTool(BaseTool):
    @property
    def name(self) -> str:
        return "dummy"

    @property
    def description(self) -> str:
        return "A test tool"

    @property
    def parameters(self) -> dict[str, Any]:
        return {"type": "object", "properties": {"msg": {"type": "string"}}}

    async def execute(self, msg: str = "", **kwargs: Any) -> ToolResult:
        return ToolResult.ok(output=f"echo: {msg}")


class TestToolRegistry:
    def test_register_and_get(self) -> None:
        registry = ToolRegistry()
        tool = DummyTool()
        registry.register(tool)
        assert registry.get("dummy") is tool
        assert "dummy" in registry.tool_names

    def test_openai_tools_format(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool())
        tools = registry.to_openai_tools()
        assert len(tools) == 1
        assert tools[0]["type"] == "function"
        assert tools[0]["function"]["name"] == "dummy"

    @pytest.mark.asyncio
    async def test_execute_known_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(DummyTool())
        result = await registry.execute("dummy", {"msg": "hello"})
        assert result.status.value == "success"
        assert "hello" in result.output

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self) -> None:
        registry = ToolRegistry()
        result = await registry.execute("nonexistent", {})
        assert result.status.value == "error"

    def test_default_registry_has_all_tools(self) -> None:
        registry = create_default_registry()
        expected = {
            "collect_facts",
            "detect_drift",
            "discover_inventory",
            "execute_playbook",
            "generate_playbook",
            "generate_rollback",
            "generate_terraform",
            "import_project",
            "inspect_variables",
            "local_exec",
            "manage_galaxy",
            "manage_git",
            "manage_inventory",
            "manage_vault",
            "memory",
            "read_file",
            "render_template",
            "request_config",
            "request_secret",
            "run_adhoc",
            "run_lint",
            "run_molecule",
            "scaffold_role",
            "search_docs",
            "session_search",
            "terraform_exec",
            "terraform_to_inventory",
            "test_connectivity",
            "verify_state",
            "web_search",
            "write_file",
        }
        assert set(registry.tool_names) == expected
