"""Tests for the FileWriter tool."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.file_writer import FileWriter


@pytest.fixture
def writer() -> FileWriter:
    return FileWriter()


class TestFileWriter:
    async def test_writes_file_under_project(self, writer: FileWriter, tmp_workspace: Path) -> None:
        body = "hello ansible"
        ws = str(tmp_workspace)
        result = await writer.execute(
            file_path="hello.txt",
            content=body,
            workspace_path=ws,
        )
        assert result.status == ToolStatus.SUCCESS
        written = tmp_workspace / "hello.txt"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == body

    async def test_writes_nested_template(self, writer: FileWriter, tmp_workspace: Path) -> None:
        body = "server { listen 80; }\n"
        ws = str(tmp_workspace)
        result = await writer.execute(
            file_path="templates/nginx.conf.j2",
            content=body,
            workspace_path=ws,
        )
        assert result.status == ToolStatus.SUCCESS
        written = tmp_workspace / "templates" / "nginx.conf.j2"
        assert written.exists()
        assert written.read_text(encoding="utf-8") == body

    async def test_rejects_path_traversal(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="../../etc/evil",
            content="malicious",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
        assert result.error is not None
        assert "escapes" in result.error.lower()

    async def test_rejects_absolute_path(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="/tmp/file_writer_escape.txt",
            content="noop",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
        assert result.error is not None
        assert "escapes" in result.error.lower()

    async def test_missing_file_path(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="",
            content="x",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
        assert "required" in (result.error or "").lower()

    async def test_missing_content(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="x.txt",
            content=None,
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.ERROR
        assert "required" in (result.error or "").lower()

    async def test_empty_content_allowed(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="empty.txt",
            content="",
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.SUCCESS
        assert (tmp_workspace / "empty.txt").exists()

    async def test_missing_workspace_path(self, writer: FileWriter, tmp_workspace: Path) -> None:
        result = await writer.execute(
            file_path="x.txt",
            content="body",
            workspace_path="",
        )
        assert result.status == ToolStatus.ERROR
        assert "required" in (result.error or "").lower()

    async def test_writes_content_verbatim(self, writer: FileWriter, tmp_workspace: Path) -> None:
        body = "---\nkey: '{{ var }}'\n{{- not jinja validated -}}\n"
        result = await writer.execute(
            file_path="templates/raw.j2",
            content=body,
            workspace_path=str(tmp_workspace),
        )
        assert result.status == ToolStatus.SUCCESS
        path = Path(result.data["path"])
        assert path.read_text(encoding="utf-8") == body
        assert path.is_relative_to(tmp_workspace.resolve())
