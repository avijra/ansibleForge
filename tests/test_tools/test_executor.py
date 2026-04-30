"""Tests for the Executor tool — specifically stale env artifact cleanup."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.tools.executor import Executor


class TestCleanStaleEnv:
    def test_removes_stale_cmdline(self, tmp_path: Path) -> None:
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        cmdline_file = env_dir / "cmdline"
        cmdline_file.write_text("--check --diff")

        Executor._clean_stale_env(tmp_path)

        assert not cmdline_file.exists()

    def test_removes_stale_extravars(self, tmp_path: Path) -> None:
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        extravars_file = env_dir / "extravars"
        extravars_file.write_text('{"ssh_password": "admin"}')

        Executor._clean_stale_env(tmp_path)

        assert not extravars_file.exists()

    def test_noop_when_env_dir_missing(self, tmp_path: Path) -> None:
        Executor._clean_stale_env(tmp_path)

    def test_preserves_other_env_files(self, tmp_path: Path) -> None:
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        settings_file = env_dir / "settings"
        settings_file.write_text("{}")
        cmdline_file = env_dir / "cmdline"
        cmdline_file.write_text("--check --diff")

        Executor._clean_stale_env(tmp_path)

        assert not cmdline_file.exists()
        assert settings_file.exists()

    def test_stale_cmdline_causes_check_mode_regression(self, tmp_path: Path) -> None:
        """Verify that a stale env/cmdline with --check --diff is cleaned
        before the runner can read it and silently switch apply to check."""
        env_dir = tmp_path / "env"
        env_dir.mkdir()
        cmdline_file = env_dir / "cmdline"
        cmdline_file.write_text("--check --diff")

        assert cmdline_file.exists()
        Executor._clean_stale_env(tmp_path)
        assert not cmdline_file.exists()
