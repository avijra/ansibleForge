"""Tests for the cross-project learning store."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.knowledge.learning_store import LearningStore


class TestLearningStore:
    def test_record_and_recall_bug_fix(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        store.record_bug_fix(
            error_pattern="ModuleNotFoundError: jmespath",
            fix_description="Install jmespath with pip",
            tool_name="execute_playbook",
        )
        results = store.recall_bugs(["jmespath"])
        assert len(results) == 1
        assert "jmespath" in results[0]["error_pattern"]

    def test_record_and_recall_pattern(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        store.record_pattern(
            pattern_name="NFD before GPU Operator",
            description="Always install NFD before GPU Operator on OpenShift",
        )
        results = store.recall_patterns(["NFD", "GPU"])
        assert len(results) == 1
        assert "NFD" in results[0]["name"]

    def test_recall_all_combines(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        store.record_bug_fix("error with ansible", "fixed it", "run_adhoc")
        store.record_pattern("Ansible best practice", "Always use FQCN")
        results = store.recall_all(["ansible"])
        assert len(results) == 2

    def test_recall_empty_keywords(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        assert store.recall_bugs([]) == []

    def test_format_context_with_entries(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        store.record_bug_fix("pip error", "install pip", "local_exec")
        ctx = store.format_context(["pip"])
        assert "CROSS-PROJECT LEARNING" in ctx
        assert "pip error" in ctx

    def test_format_context_empty(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        assert store.format_context(["nonexistent"]) == ""

    def test_enforce_limit(self, tmp_path: Path):
        store = LearningStore(tmp_path / "learning")
        for i in range(105):
            store.record_bug_fix(f"error {i}", f"fix {i}", f"tool_{i}")
        bug_files = list((tmp_path / "learning" / "bugs").glob("*.json"))
        assert len(bug_files) <= 100
