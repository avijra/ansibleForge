"""Tests for the MemoryTool and WorkspaceMemory."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.knowledge.workspace_memory import WorkspaceMemory
from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.memory_tool import MemoryTool


@pytest.fixture
def mem_dir(tmp_path: Path) -> Path:
    return tmp_path / "workspaces"


@pytest.fixture
def memory(mem_dir: Path) -> WorkspaceMemory:
    return WorkspaceMemory("test-ws", base_dir=mem_dir)


@pytest.fixture
def tool() -> MemoryTool:
    return MemoryTool()


class TestWorkspaceMemory:
    def test_read_empty(self, memory: WorkspaceMemory) -> None:
        assert memory.read() == ""

    def test_add_and_read(self, memory: WorkspaceMemory) -> None:
        result = memory.add("SSH uses port 2222 on this host")
        assert "Added" in result
        assert "SSH uses port 2222" in memory.read()

    def test_add_multiple(self, memory: WorkspaceMemory) -> None:
        memory.add("Fact A")
        memory.add("Fact B")
        content = memory.read()
        assert "Fact A" in content
        assert "Fact B" in content

    def test_replace(self, memory: WorkspaceMemory) -> None:
        memory.add("Port is 22")
        result = memory.replace("Port is 22", "Port is 2222")
        assert "Replaced" in result
        assert "Port is 2222" in memory.read()
        assert "Port is 22\n" not in memory.read()

    def test_replace_not_found(self, memory: WorkspaceMemory) -> None:
        memory.add("Fact A")
        result = memory.replace("nonexistent", "new")
        assert "not found" in result.lower()

    def test_remove(self, memory: WorkspaceMemory) -> None:
        memory.add("keep this")
        memory.add("delete this")
        result = memory.remove("delete")
        assert "Removed 1" in result
        assert "keep this" in memory.read()
        assert "delete" not in memory.read()

    def test_clear(self, memory: WorkspaceMemory) -> None:
        memory.add("data")
        result = memory.clear()
        assert "cleared" in result.lower()
        assert memory.read() == ""

    def test_size_limit(self, memory: WorkspaceMemory) -> None:
        big = "x" * 3001
        result = memory.add(big)
        assert "exceeds" in result.lower()

    def test_inject_context_empty(self, memory: WorkspaceMemory) -> None:
        assert memory.inject_context() == ""

    def test_inject_context_with_data(self, memory: WorkspaceMemory) -> None:
        memory.add("Important fact")
        ctx = memory.inject_context()
        assert "MEMORY.md" in ctx
        assert "Important fact" in ctx


class TestMemoryTool:
    async def test_read_empty(self, tool: MemoryTool, tmp_path: Path) -> None:
        result = await tool.execute(action="read", workspace_path=str(tmp_path))
        assert result.status == ToolStatus.SUCCESS
        assert "empty" in result.output.lower()

    async def test_add_and_read(self, tool: MemoryTool, tmp_path: Path) -> None:
        ws = str(tmp_path)
        result = await tool.execute(action="add", entry="Test fact", workspace_path=ws)
        assert result.status == ToolStatus.SUCCESS
        assert "Added" in result.output

        result = await tool.execute(action="read", workspace_path=ws)
        assert "Test fact" in result.output

    async def test_add_missing_entry(self, tool: MemoryTool, tmp_path: Path) -> None:
        result = await tool.execute(action="add", workspace_path=str(tmp_path))
        assert result.status == ToolStatus.ERROR

    async def test_replace(self, tool: MemoryTool, tmp_path: Path) -> None:
        ws = str(tmp_path)
        await tool.execute(action="add", entry="old value", workspace_path=ws)
        result = await tool.execute(
            action="replace", old_text="old value", new_text="new value", workspace_path=ws,
        )
        assert result.status == ToolStatus.SUCCESS

    async def test_remove(self, tool: MemoryTool, tmp_path: Path) -> None:
        ws = str(tmp_path)
        await tool.execute(action="add", entry="removable line", workspace_path=ws)
        result = await tool.execute(action="remove", pattern="removable", workspace_path=ws)
        assert result.status == ToolStatus.SUCCESS
        assert "Removed" in result.output

    async def test_clear(self, tool: MemoryTool, tmp_path: Path) -> None:
        ws = str(tmp_path)
        await tool.execute(action="add", entry="data", workspace_path=ws)
        result = await tool.execute(action="clear", workspace_path=ws)
        assert result.status == ToolStatus.SUCCESS

    async def test_unknown_action(self, tool: MemoryTool, tmp_path: Path) -> None:
        result = await tool.execute(action="bogus", workspace_path=str(tmp_path))
        assert result.status == ToolStatus.ERROR
