"""Tests for shared ansible-runner diagnostics."""

from __future__ import annotations

from ansible_forge.tools._runner_diagnostics import (
    diagnose_runner_failure,
    read_runner_stdout,
)


class _FakeStdout:
    def __init__(self, text: str) -> None:
        self._text = text
        self._pos = 0

    def read(self) -> str:
        return self._text

    def seek(self, pos: int) -> None:
        self._pos = pos


class TestRunnerDiagnostics:
    def test_diagnose_pre_runner_locale_failure(self) -> None:
        raw = (
            "ERROR: Ansible could not initialize the preferred locale: "
            "unsupported locale setting\n"
        )
        diag = diagnose_runner_failure([], raw_stdout=raw, rc=1)
        assert "unsupported locale setting" in diag
        assert "before any tasks ran" in diag

    def test_diagnose_task_failure_takes_priority(self) -> None:
        events = [
            {
                "event": "runner_on_failed",
                "task": "Install package",
                "host": "web1",
                "result": {"msg": "permission denied"},
            }
        ]
        diag = diagnose_runner_failure(
            events,
            raw_stdout="ERROR: locale",
            rc=1,
        )
        assert 'FAILED task "Install package" on web1' in diag

    def test_read_runner_stdout_from_file_like(self) -> None:
        runner = type("Runner", (), {"stdout": _FakeStdout("hello\n")})()
        assert read_runner_stdout(runner) == "hello\n"

    def test_diagnose_non_zero_with_lfstack_signature(self) -> None:
        events = [
            {
                "event": "runner_on_failed",
                "task": "Verify openshift-install binary",
                "host": "localhost",
                "result": {"msg": "non-zero return code"},
            }
        ]
        raw = "runtime: lfstack.push invalid packing\nfatal error: lfstack.push"
        diag = diagnose_runner_failure(events, raw_stdout=raw, rc=2)
        assert "Likely architecture mismatch" in diag
        assert "arm64 EE container" in diag
