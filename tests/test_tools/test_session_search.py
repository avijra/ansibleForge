"""Tests for the SessionSearchTool and SessionStore FTS."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.persistence.session_store import SessionStore
from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.session_search import SessionSearchTool


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(db_path=tmp_path / "test_sessions.db")


@pytest.fixture
def seeded_store(store: SessionStore) -> SessionStore:
    store.save_session("s1", title="GPU Operator Setup", project_path="/tmp/test")
    store.save_event("s1", "message", {"content": "Installing NVIDIA GPU operator on OpenShift cluster"})
    store.save_event("s1", "tool_result", {"output": "BundleUnpackFailed: DeadlineExceeded"})
    store.save_event("s1", "message", {"content": "Operator installation completed successfully"})

    store.save_session("s2", title="Ansible Playbook Debug", project_path="/tmp/test2")
    store.save_event("s2", "message", {"content": "Running playbook for nginx configuration"})
    store.save_event("s2", "tool_result", {"output": "Task failed: package nginx not found"})
    return store


class TestSessionStoreFTS:
    def test_search_returns_results(self, seeded_store: SessionStore) -> None:
        results = seeded_store.search_events("GPU operator", limit=5)
        assert len(results) > 0
        assert any("GPU" in r.get("excerpt", "") or "GPU" in r.get("session_title", "") for r in results)

    def test_search_no_match(self, seeded_store: SessionStore) -> None:
        results = seeded_store.search_events("xyznonexistent", limit=5)
        assert len(results) == 0

    def test_search_empty_query(self, seeded_store: SessionStore) -> None:
        results = seeded_store.search_events("", limit=5)
        assert len(results) == 0

    def test_fts_backfill(self, tmp_path: Path) -> None:
        # Arrange: create store, insert events
        store = SessionStore(db_path=tmp_path / "backfill.db")
        store.save_session("s1", title="Test")
        store.save_event("s1", "message", {"content": "kubernetes cluster deployment"})

        # Act: search should find it via the triggers
        results = store.search_events("kubernetes cluster", limit=5)
        assert len(results) > 0

    def test_delete_trigger(self, seeded_store: SessionStore) -> None:
        results_before = seeded_store.search_events("nginx", limit=5)
        seeded_store.delete_session("s2")
        results_after = seeded_store.search_events("nginx", limit=5)
        assert len(results_after) < len(results_before) or len(results_after) == 0


class TestSessionSearchTool:
    async def test_search_success(self, seeded_store: SessionStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ansible_forge.persistence.session_store.SessionStore.get_instance",
            staticmethod(lambda *a, **kw: seeded_store),
        )
        tool = SessionSearchTool()
        result = await tool.execute(query="GPU operator")
        assert result.status == ToolStatus.SUCCESS

    async def test_search_empty_query(self) -> None:
        tool = SessionSearchTool()
        result = await tool.execute(query="")
        assert result.status == ToolStatus.ERROR

    async def test_search_no_results(self, seeded_store: SessionStore, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "ansible_forge.persistence.session_store.SessionStore.get_instance",
            staticmethod(lambda *a, **kw: seeded_store),
        )
        tool = SessionSearchTool()
        result = await tool.execute(query="xyznonexistent")
        assert result.status == ToolStatus.SUCCESS
        assert "no matching" in result.output.lower()
