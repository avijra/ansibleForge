"""Tests for the RoleScaffolder tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.role_scaffolder import RoleScaffolder


@pytest.fixture
def scaffolder() -> RoleScaffolder:
    return RoleScaffolder()


class TestRoleScaffolder:
    @pytest.mark.asyncio
    async def test_scaffolds_role_structure(
        self, scaffolder: RoleScaffolder, tmp_workspace: Path
    ) -> None:
        result = await scaffolder.execute(
            role_name="nginx",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.SUCCESS
        role_path = tmp_workspace / "roles" / "nginx"
        for subdir in ("tasks", "handlers", "defaults", "meta", "templates", "files", "vars"):
            assert (role_path / subdir).is_dir()
        assert (role_path / "tasks" / "main.yml").exists()
        meta = (role_path / "meta" / "main.yml").read_text()
        assert "namespace: tuyere" in meta
        assert 'role_name: "nginx"' in meta

    @pytest.mark.asyncio
    async def test_custom_tasks_content(
        self, scaffolder: RoleScaffolder, tmp_workspace: Path
    ) -> None:
        custom_tasks = "---\n- name: Custom task\n  ansible.builtin.debug:\n    msg: custom\n"
        result = await scaffolder.execute(
            role_name="custom",
            workspace_path=str(tmp_workspace),
            tasks_content=custom_tasks,
        )
        assert result.status == ToolStatus.SUCCESS
        content = (tmp_workspace / "roles" / "custom" / "tasks" / "main.yml").read_text()
        assert "Custom task" in content

    @pytest.mark.asyncio
    async def test_templates_written(
        self, scaffolder: RoleScaffolder, tmp_workspace: Path
    ) -> None:
        result = await scaffolder.execute(
            role_name="web",
            workspace_path=str(tmp_workspace),
            templates={"nginx.conf.j2": "server { listen 80; }"},
        )
        assert result.status == ToolStatus.SUCCESS
        tpl = tmp_workspace / "roles" / "web" / "templates" / "nginx.conf.j2"
        assert tpl.exists()
        assert "listen 80" in tpl.read_text()

    @pytest.mark.asyncio
    async def test_missing_params(self, scaffolder: RoleScaffolder) -> None:
        result = await scaffolder.execute()
        assert result.status == ToolStatus.ERROR
