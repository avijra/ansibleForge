"""Tests for the RollbackPlanner."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.safety.rollback import RollbackPlanner
from ansible_forge.tools.base import ToolStatus


@pytest.fixture
def planner() -> RollbackPlanner:
    return RollbackPlanner()


class TestRollbackPlanner:
    def test_generates_rollback_for_service(
        self, planner: RollbackPlanner, tmp_workspace: Path
    ) -> None:
        playbook = (
            "---\n"
            "- name: Start services\n"
            "  hosts: all\n"
            "  become: true\n"
            "  tasks:\n"
            "    - name: Start nginx\n"
            "      ansible.builtin.service:\n"
            "        name: nginx\n"
            "        state: started\n"
        )
        (tmp_workspace / "project" / "services.yml").write_text(playbook)
        result = planner.generate(str(tmp_workspace), "services.yml")
        assert result.status == ToolStatus.SUCCESS
        assert result.data.get("rollback_needed")
        assert (tmp_workspace / "project" / "rollback_services.yml").exists()

    def test_no_rollback_for_safe_playbook(
        self, planner: RollbackPlanner, tmp_workspace: Path, sample_playbook: str
    ) -> None:
        (tmp_workspace / "project" / "safe.yml").write_text(sample_playbook)
        result = planner.generate(str(tmp_workspace), "safe.yml")
        assert result.status == ToolStatus.SUCCESS
        assert not result.data.get("rollback_needed")

    def test_missing_playbook(
        self, planner: RollbackPlanner, tmp_workspace: Path
    ) -> None:
        result = planner.generate(str(tmp_workspace), "missing.yml")
        assert result.status == ToolStatus.ERROR
