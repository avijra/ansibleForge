"""Tests for the WorkspaceManager."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.workspace.manager import WorkspaceManager


class TestWorkspaceManager:
    def test_create_workspace(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        ws = mgr.create("test-session")
        assert ws.session_id == "test-session"
        assert ws.path.exists()
        assert ws.project_dir.exists()
        assert ws.inventory_dir.exists()
        assert ws.env_dir.exists()
        assert ws.artifacts_dir.exists()
        assert (ws.path / ".tuyere" / ".gitignore").exists()

    def test_get_workspace(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        mgr.create("sess1")
        ws = mgr.get("sess1")
        assert ws is not None
        assert ws.session_id == "sess1"

    def test_get_nonexistent_returns_none(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        assert mgr.get("missing") is None

    def test_destroy_cleans_runner_dir(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        ws = mgr.create("to-delete")
        runner_dir = ws.path / ".tuyere"
        assert runner_dir.exists()
        assert mgr.destroy("to-delete")
        assert not runner_dir.exists()
        assert ws.path.exists()

    def test_workspace_to_dict(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        ws = mgr.create("dict-test")
        d = ws.to_dict()
        assert d["session_id"] == "dict-test"
        assert "path" in d

    def test_create_with_project_path(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        project_dir = tmp_path / "my-infra"
        ws = mgr.create("proj-session", project_path=project_dir)
        assert ws.path == project_dir
        assert ws.project_dir == project_dir
        assert (project_dir / ".tuyere").exists()
        assert (project_dir / ".tuyere" / ".gitignore").exists()
        assert (project_dir / "inventory").exists()

    def test_get_by_path(self, tmp_path: Path) -> None:
        mgr = WorkspaceManager(base_dir=tmp_path)
        project_dir = tmp_path / "my-project"
        project_dir.mkdir()
        ws = mgr.get_by_path(project_dir)
        assert ws is not None
        assert ws.path == project_dir
