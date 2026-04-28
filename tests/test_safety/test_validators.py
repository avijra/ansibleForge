"""Tests for the pre-execution validators."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.safety.validators import PlaybookValidator


@pytest.fixture
def validator() -> PlaybookValidator:
    return PlaybookValidator()


class TestPlaybookValidator:
    def test_valid_playbook_passes(
        self, validator: PlaybookValidator, tmp_workspace: Path, sample_playbook: str
    ) -> None:
        (tmp_workspace / "project" / "safe.yml").write_text(sample_playbook)
        result = validator.validate(str(tmp_workspace), "safe.yml")
        assert result.passed
        assert len(result.errors) == 0

    def test_dangerous_rm_rf_blocked(
        self, validator: PlaybookValidator, tmp_workspace: Path, dangerous_playbook: str
    ) -> None:
        (tmp_workspace / "project" / "danger.yml").write_text(dangerous_playbook)
        result = validator.validate(str(tmp_workspace), "danger.yml")
        assert not result.passed
        error_rules = [i.rule for i in result.errors]
        assert "dangerous_pattern" in error_rules or "dangerous_command" in error_rules

    def test_broad_privilege_escalation_warned(
        self, validator: PlaybookValidator, tmp_workspace: Path
    ) -> None:
        playbook = (
            "---\n"
            "- name: Broad become\n"
            "  hosts: all\n"
            "  become: true\n"
            "  tasks:\n"
            "    - name: Debug\n"
            "      ansible.builtin.debug:\n"
            "        msg: test\n"
        )
        (tmp_workspace / "project" / "broad.yml").write_text(playbook)
        result = validator.validate(str(tmp_workspace), "broad.yml")
        warning_rules = [i.rule for i in result.warnings]
        assert "broad_privilege_escalation" in warning_rules

    def test_missing_playbook(
        self, validator: PlaybookValidator, tmp_workspace: Path
    ) -> None:
        result = validator.validate(str(tmp_workspace), "nonexistent.yml")
        assert not result.passed

    def test_invalid_yaml(
        self, validator: PlaybookValidator, tmp_workspace: Path
    ) -> None:
        (tmp_workspace / "project" / "bad.yml").write_text("{{broken yaml")
        result = validator.validate(str(tmp_workspace), "bad.yml")
        assert not result.passed


class TestValidationResult:
    def test_to_dict(
        self, validator: PlaybookValidator, tmp_workspace: Path, sample_playbook: str
    ) -> None:
        (tmp_workspace / "project" / "test.yml").write_text(sample_playbook)
        result = validator.validate(str(tmp_workspace), "test.yml")
        d = result.to_dict()
        assert "passed" in d
        assert "error_count" in d
        assert "issues" in d
