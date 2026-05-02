"""Tests for the PlaybookGenerator tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.playbook_generator import PlaybookGenerator


@pytest.fixture
def generator() -> PlaybookGenerator:
    return PlaybookGenerator()


class TestPlaybookGenerator:
    @pytest.mark.asyncio
    async def test_generates_valid_playbook(
        self, generator: PlaybookGenerator, tmp_workspace: Path
    ) -> None:
        content = (
            "---\n"
            "- name: Install nginx\n"
            "  hosts: webservers\n"
            "  tasks:\n"
            "    - name: Install nginx package\n"
            "      ansible.builtin.apt:\n"
            "        name: nginx\n"
            "        state: present\n"
        )
        result = await generator.execute(
            playbook_name="install_nginx.yml",
            content=content,
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.SUCCESS
        assert (tmp_workspace / "install_nginx.yml").exists()

    @pytest.mark.asyncio
    async def test_adds_yml_extension(
        self, generator: PlaybookGenerator, tmp_workspace: Path
    ) -> None:
        content = "---\n- name: Test\n  hosts: all\n  tasks: []\n"
        result = await generator.execute(
            playbook_name="test_play",
            content=content,
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.SUCCESS
        assert "test_play.yml" in result.output

    @pytest.mark.asyncio
    async def test_rejects_invalid_yaml(
        self, generator: PlaybookGenerator, tmp_workspace: Path
    ) -> None:
        result = await generator.execute(
            playbook_name="bad.yml",
            content="{{invalid yaml:::}}",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR

    @pytest.mark.asyncio
    async def test_rejects_non_list_yaml(
        self, generator: PlaybookGenerator, tmp_workspace: Path
    ) -> None:
        result = await generator.execute(
            playbook_name="bad.yml",
            content="key: value\n",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
        assert "list" in (result.error or "").lower()

    @pytest.mark.asyncio
    async def test_missing_params(self, generator: PlaybookGenerator) -> None:
        result = await generator.execute()
        assert result.status == ToolStatus.ERROR


class TestPlaybookGeneratorSchema:
    def test_tool_name(self, generator: PlaybookGenerator) -> None:
        assert generator.name == "generate_playbook"

    def test_openai_tool_schema(self, generator: PlaybookGenerator) -> None:
        schema = generator.to_openai_tool()
        assert schema["type"] == "function"
        assert "parameters" in schema["function"]
        assert "playbook_name" in schema["function"]["parameters"]["properties"]
