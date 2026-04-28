"""Tests for the InventoryManager tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.inventory_manager import InventoryManager


@pytest.fixture
def inv_mgr() -> InventoryManager:
    return InventoryManager()


class TestInventoryManager:
    @pytest.mark.asyncio
    async def test_create_inventory(
        self, inv_mgr: InventoryManager, tmp_workspace: Path
    ) -> None:
        content = "all:\n  hosts:\n    web1:\n      ansible_host: 10.0.0.1\n"
        result = await inv_mgr.execute(
            action="create",
            workspace_path=str(tmp_workspace),
            content=content,
        )
        assert result.status == ToolStatus.SUCCESS
        assert (tmp_workspace / "inventory" / "hosts.yml").exists()

    @pytest.mark.asyncio
    async def test_add_host(
        self, inv_mgr: InventoryManager, tmp_workspace: Path
    ) -> None:
        result = await inv_mgr.execute(
            action="add_host",
            workspace_path=str(tmp_workspace),
            host="db1",
            group="databases",
            variables={"ansible_host": "10.0.0.5"},
        )
        assert result.status == ToolStatus.SUCCESS
        inv = (tmp_workspace / "inventory" / "hosts.yml").read_text()
        assert "db1" in inv
        assert "databases" in inv

    @pytest.mark.asyncio
    async def test_add_group(
        self, inv_mgr: InventoryManager, tmp_workspace: Path
    ) -> None:
        result = await inv_mgr.execute(
            action="add_group",
            workspace_path=str(tmp_workspace),
            group="monitoring",
            variables={"monitor_port": 9090},
        )
        assert result.status == ToolStatus.SUCCESS
        inv = (tmp_workspace / "inventory" / "hosts.yml").read_text()
        assert "monitoring" in inv

    @pytest.mark.asyncio
    async def test_read_nonexistent(
        self, inv_mgr: InventoryManager, tmp_workspace: Path
    ) -> None:
        result = await inv_mgr.execute(
            action="read",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
