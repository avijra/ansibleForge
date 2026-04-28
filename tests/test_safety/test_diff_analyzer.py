"""Tests for the DiffAnalyzer."""

from __future__ import annotations

import pytest

from ansible_forge.safety.diff_analyzer import DiffAnalyzer


@pytest.fixture
def analyzer() -> DiffAnalyzer:
    return DiffAnalyzer()


class TestDiffAnalyzer:
    def test_no_changes(self, analyzer: DiffAnalyzer) -> None:
        report = analyzer.analyze([])
        assert not report.has_changes
        assert "No changes" in report.summary()

    def test_changed_events(self, analyzer: DiffAnalyzer) -> None:
        events = [
            {
                "event": "runner_on_changed",
                "host": "web1",
                "task": "Install nginx",
                "result": {"changed": True, "msg": "package installed"},
            }
        ]
        report = analyzer.analyze(events)
        assert report.has_changes
        assert len(report.changes) == 1
        assert report.changes[0].host == "web1"

    def test_failed_events(self, analyzer: DiffAnalyzer) -> None:
        events = [
            {
                "event": "runner_on_failed",
                "host": "db1",
                "task": "Start service",
                "result": {"msg": "service not found"},
            }
        ]
        report = analyzer.analyze(events)
        assert report.has_failures

    def test_report_to_dict(self, analyzer: DiffAnalyzer) -> None:
        events = [
            {
                "event": "runner_on_changed",
                "host": "web1",
                "task": "Test",
                "result": {"changed": True, "diff": {"before": "a", "after": "b"}},
            }
        ]
        report = analyzer.analyze(events)
        d = report.to_dict()
        assert d["change_count"] == 1
        assert "summary" in d
