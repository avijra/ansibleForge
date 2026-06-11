"""Tests for LintRunner target resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.tools.lint_runner import LintRunner


class TestLintRunner:
    def test_resolve_relative_role_against_workspace(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "roles" / "demo"
        role_dir.mkdir(parents=True)
        (role_dir / "tasks").mkdir()
        (role_dir / "tasks" / "main.yml").write_text("---\n", encoding="utf-8")

        resolved = LintRunner._resolve_target("roles/demo", str(tmp_path))
        assert resolved == role_dir

    @pytest.mark.asyncio
    async def test_missing_relative_target_requires_workspace(self, tmp_path: Path) -> None:
        runner = LintRunner()
        result = await runner.execute(
            target="roles/missing",
            workspace_path=str(tmp_path),
        )
        assert result.status.value == "error"
        assert "Target not found" in (result.error or "")
