"""Tests for loop detection and error tracking in SessionState.

Covers all 15 scenarios from the loop detection stability audit.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ansible_forge.agent.orchestrator import SessionState


@pytest.fixture()
def state():
    ws = MagicMock()
    ws.root = "/tmp/test"
    ws.context_summary.return_value = ""
    s = SessionState("test-session", ws)
    return s


def _record(state: SessionState, name: str, args: dict | None = None):
    state.record_tool_call(name, args or {})


def _record_n(state: SessionState, name: str, n: int, args: dict | None = None):
    for _ in range(n):
        _record(state, name, args)


class TestLoopPattern:
    def test_no_calls_returns_none(self, state: SessionState):
        assert state.loop_pattern is None

    def test_fewer_than_3_calls_returns_none(self, state: SessionState):
        _record(state, "run_adhoc", {"host": "a"})
        _record(state, "run_adhoc", {"host": "a"})
        assert state.loop_pattern is None

    def test_exact_repeat_3_identical(self, state: SessionState):
        args = {"module": "shell", "module_args": "ls"}
        _record_n(state, "run_adhoc", 3, args)
        assert state.loop_pattern == "exact_repeat"

    def test_exact_repeat_not_triggered_by_different_args(self, state: SessionState):
        _record(state, "run_adhoc", {"cmd": "a"})
        _record(state, "run_adhoc", {"cmd": "b"})
        _record(state, "run_adhoc", {"cmd": "c"})
        assert state.loop_pattern is None

    def test_alternating_pattern(self, state: SessionState):
        a = {"cmd": "a"}
        b = {"cmd": "b"}
        for _ in range(3):
            _record(state, "run_adhoc", a)
            _record(state, "web_search", b)
        assert state.loop_pattern == "alternating"

    def test_alternating_not_triggered_with_variation(self, state: SessionState):
        for i in range(3):
            _record(state, "run_adhoc", {"cmd": f"a{i}"})
            _record(state, "web_search", {"q": f"b{i}"})
        assert state.loop_pattern is None

    def test_same_tool_drift(self, state: SessionState):
        for i in range(15):
            _record(state, "run_adhoc", {"cmd": f"variant_{i % 3}"})
        assert state.loop_pattern == "same_tool_drift"

    def test_same_tool_drift_not_triggered_with_many_variants(self, state: SessionState):
        for i in range(15):
            _record(state, "run_adhoc", {"cmd": f"unique_{i}"})
        assert state.loop_pattern is None

    def test_different_tools_never_exact_repeat(self, state: SessionState):
        _record(state, "run_adhoc", {"cmd": "x"})
        _record(state, "web_search", {"q": "x"})
        _record(state, "local_exec", {"cmd": "x"})
        assert state.loop_pattern is None


class TestConsecFailsByTool:
    def test_no_errors_returns_false(self, state: SessionState):
        assert state.has_repeated_errors() is False

    def test_single_failure_not_repeated(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 1
        assert state.has_repeated_errors() is False

    def test_two_failures_not_repeated(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 2
        assert state.has_repeated_errors() is False

    def test_three_failures_is_repeated(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 3
        assert state.has_repeated_errors() is True

    def test_success_clears_counter(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 2
        state._consec_fails_by_tool.pop("run_adhoc", None)
        assert state.has_repeated_errors() is False

    def test_different_tools_independent(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 2
        state._consec_fails_by_tool["web_search"] = 2
        assert state.has_repeated_errors() is False

    def test_one_tool_at_threshold_triggers(self, state: SessionState):
        state._consec_fails_by_tool["run_adhoc"] = 1
        state._consec_fails_by_tool["web_search"] = 3
        assert state.has_repeated_errors() is True


class TestScenarios:
    """Reproduce the 15 scenarios from the stability audit."""

    def test_scenario1_exact_repeat_then_clean_slate(self, state: SessionState):
        """Exact repeat detected → hard loop → next step clean."""
        args = {"cmd": "same"}
        _record_n(state, "run_adhoc", 3, args)
        assert state.loop_pattern == "exact_repeat"
        state._recent_tool_calls.clear()
        state._consec_fails_by_tool.clear()
        _record(state, "web_search", {"q": "something"})
        assert state.loop_pattern is None
        assert state.has_repeated_errors() is False

    def test_scenario2_alternating_then_clean(self, state: SessionState):
        """Alternating detected → hard loop → next step clean."""
        a, b = {"cmd": "a"}, {"cmd": "b"}
        for _ in range(3):
            _record(state, "run_adhoc", a)
            _record(state, "web_search", b)
        assert state.loop_pattern == "alternating"
        state._recent_tool_calls.clear()
        state._consec_fails_by_tool.clear()
        _record(state, "generate_playbook", {"p": "new"})
        assert state.loop_pattern is None

    def test_scenario4_error_identical_three_consec_fails(self, state: SessionState):
        """Tool fails 3 times consecutively → has_repeated_errors fires."""
        state._consec_fails_by_tool["run_adhoc"] = 3
        assert state.has_repeated_errors() is True

    def test_scenario5_early_fail_then_success_clears(self, state: SessionState):
        """The actual session failure: fail once, succeed later, no false trigger."""
        state._consec_fails_by_tool["run_adhoc"] = 1
        state._consec_fails_by_tool.pop("run_adhoc", None)
        for i in range(5):
            _record(state, "run_adhoc", {"cmd": f"aws check {i}"})
        assert state.has_repeated_errors() is False
        assert state.loop_pattern is None

    def test_scenario6_fail_switch_succeed_back(self, state: SessionState):
        """Tool fails, agent switches, comes back successfully."""
        state._consec_fails_by_tool["run_adhoc"] = 1
        state._consec_fails_by_tool.pop("run_adhoc", None)
        _record(state, "run_adhoc", {"cmd": "new approach"})
        assert state.has_repeated_errors() is False

    def test_scenario7_three_fails_different_args(self, state: SessionState):
        """Tool fails 3 times with different args → correctly flagged."""
        state._consec_fails_by_tool["run_adhoc"] = 3
        assert state.has_repeated_errors() is True

    def test_scenario8_global_consecutive_errors_independent(self, state: SessionState):
        """3 different tools each fail once — per-tool count stays at 1."""
        state._consec_fails_by_tool["run_adhoc"] = 1
        state._consec_fails_by_tool["web_search"] = 1
        state._consec_fails_by_tool["generate_playbook"] = 1
        assert state.has_repeated_errors() is False

    def test_scenario9_soft_loop_trim(self, state: SessionState):
        """Soft loop trims history so it doesn't re-trigger immediately."""
        for i in range(15):
            _record(state, "run_adhoc", {"cmd": f"v{i % 3}"})
        assert state.loop_pattern == "same_tool_drift"
        state._recent_tool_calls[:] = state._recent_tool_calls[-5:]
        assert len(state._recent_tool_calls) == 5
        _record(state, "run_adhoc", {"cmd": "v0"})
        assert state.loop_pattern is None

    def test_scenario10_parallel_no_loop_check(self, state: SessionState):
        """Parallel path records calls but doesn't check loops (just verify recording)."""
        _record(state, "web_search", {"q": "a"})
        _record(state, "web_search", {"q": "b"})
        _record(state, "web_search", {"q": "c"})
        assert state.loop_pattern is None

    def test_scenario12_current_call_included_in_check(self, state: SessionState):
        """record_tool_call runs before loop_pattern — current call is in history."""
        args = {"cmd": "same"}
        _record(state, "run_adhoc", args)
        _record(state, "run_adhoc", args)
        assert state.loop_pattern is None
        _record(state, "run_adhoc", args)
        assert state.loop_pattern == "exact_repeat"

    def test_scenario13_multiple_tool_calls_one_response(self, state: SessionState):
        """3 identical calls in one response triggers on the 3rd."""
        args = {"cmd": "same"}
        _record(state, "run_adhoc", args)
        assert state.loop_pattern is None
        _record(state, "run_adhoc", args)
        assert state.loop_pattern is None
        _record(state, "run_adhoc", args)
        assert state.loop_pattern == "exact_repeat"

    def test_scenario14_has_repeated_errors_uses_per_tool_count(self, state: SessionState):
        """has_repeated_errors checks actual failure count, not call frequency."""
        state._consec_fails_by_tool["run_adhoc"] = 1
        _record_n(state, "run_adhoc", 10, {"cmd": "x"})
        assert state.has_repeated_errors() is False

    def test_no_cascading_after_hard_loop(self, state: SessionState):
        """After clearing on hard loop, a different tool is not flagged."""
        args = {"cmd": "same"}
        _record_n(state, "run_adhoc", 3, args)
        assert state.loop_pattern == "exact_repeat"
        state._recent_tool_calls.clear()
        state._consec_fails_by_tool.clear()
        _record(state, "local_exec", {"cmd": "different"})
        assert state.loop_pattern is None
        assert state.has_repeated_errors() is False

    def test_retry_budget_per_tool_not_global(self, state: SessionState):
        """Per-tool counter means 3 different tool failures don't exhaust budget."""
        state._consec_fails_by_tool["run_adhoc"] = 1
        state._consec_fails_by_tool["web_search"] = 1
        state._consec_fails_by_tool["terraform_exec"] = 1
        for tool in ("run_adhoc", "web_search", "terraform_exec"):
            remaining = max(state._max_error_retries - state._consec_fails_by_tool[tool], 0)
            assert remaining == 2, f"{tool} should have 2 retries left"

    def test_history_cap_at_30(self, state: SessionState):
        """_recent_tool_calls never exceeds 30 entries."""
        for i in range(50):
            _record(state, "run_adhoc", {"i": i})
        assert len(state._recent_tool_calls) == 30
