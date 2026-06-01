"""Tests for orchestrator gates: verify gate and false-completion guard."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ansible_forge.agent.orchestrator import Orchestrator, SessionState
from ansible_forge.tools.base import ToolStatus


@pytest.fixture()
def state():
    ws = MagicMock()
    ws.root = "/tmp/test"
    ws.context_summary.return_value = ""
    return SessionState("test-session", ws)


class TestPostApplyVerificationGate:
    def test_no_pending_returns_none(self, state: SessionState):
        result = Orchestrator._check_post_apply_verification_gate(
            state, "generate_playbook",
        )
        assert result is None

    def test_blocks_non_exempt_tool_when_pending(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        result = Orchestrator._check_post_apply_verification_gate(
            state, "generate_playbook",
        )
        assert result is not None
        assert result.status == ToolStatus.ERROR
        assert "BLOCKED" in result.output
        assert "deploy.yml" in result.output

    def test_allows_verify_state_when_pending(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        result = Orchestrator._check_post_apply_verification_gate(
            state, "verify_state",
        )
        assert result is None

    def test_allows_read_file_when_pending(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        result = Orchestrator._check_post_apply_verification_gate(
            state, "read_file",
        )
        assert result is None

    def test_allows_web_search_when_pending(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        result = Orchestrator._check_post_apply_verification_gate(
            state, "web_search",
        )
        assert result is None

    def test_auto_releases_after_max_blocks(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")

        # Block 1
        r1 = Orchestrator._check_post_apply_verification_gate(
            state, "scaffold_role",
        )
        assert r1 is not None

        # Block 2
        r2 = Orchestrator._check_post_apply_verification_gate(
            state, "scaffold_role",
        )
        assert r2 is not None

        # Block 3 — auto-release
        r3 = Orchestrator._check_post_apply_verification_gate(
            state, "scaffold_role",
        )
        assert r3 is None
        assert len(state._pending_verifications) == 0

    def test_multiple_artifacts_tracked(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        state._pending_verifications.add("terraform:prod")
        result = Orchestrator._check_post_apply_verification_gate(
            state, "generate_playbook",
        )
        assert result is not None
        assert "deploy.yml" in result.output
        assert "terraform:prod" in result.output


class TestFalseCompletionGuard:
    def test_no_issues_returns_none(self, state: SessionState):
        result = Orchestrator._check_false_completion(state)
        assert result is None

    def test_rejects_when_pending_verifications(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        result = Orchestrator._check_false_completion(state)
        assert result is not None
        assert "COMPLETION REJECTED" in result
        assert "deploy.yml" in result
        assert state._false_completion_rejects == 1

    def test_rejects_when_plan_steps_incomplete(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "action": "research", "tool": "web_search", "status": "done"},
                {"step": 2, "action": "generate", "tool": "generate_playbook", "status": "pending"},
                {"step": 3, "action": "execute", "tool": "execute_playbook", "status": "pending"},
                {"step": 4, "action": "verify", "tool": "verify_state", "status": "pending"},
            ],
            "status": "planned",
        }
        state.step_count = 2
        state.record_tool_call("web_search", {"q": "test"})
        result = Orchestrator._check_false_completion(state)
        assert result is not None
        assert "COMPLETION REJECTED" in result

    def test_accepts_after_max_rejects(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")

        # Reject 1
        r1 = Orchestrator._check_false_completion(state)
        assert r1 is not None

        # Reject 2
        r2 = Orchestrator._check_false_completion(state)
        assert r2 is not None

        # Accept (max rejects reached)
        r3 = Orchestrator._check_false_completion(state)
        assert r3 is None

    def test_no_false_positive_on_trivial_plan(self, state: SessionState):
        state.plan = {
            "steps": [{"step": 1, "action": "explain", "tool": ""}],
            "status": "planned",
        }
        result = Orchestrator._check_false_completion(state)
        assert result is None

    def test_no_false_positive_on_empty_plan(self, state: SessionState):
        state.plan = {"steps": [], "status": "planned"}
        result = Orchestrator._check_false_completion(state)
        assert result is None

    def test_no_false_positive_when_all_steps_done(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "done"},
                {"step": 2, "tool": "generate_playbook", "status": "done"},
                {"step": 3, "tool": "execute_playbook", "status": "done"},
            ],
            "status": "planned",
        }
        state.record_tool_call("web_search", {"q": "test"})
        state.record_tool_call("generate_playbook", {"name": "test"})
        state.record_tool_call("execute_playbook", {"playbook": "test"})
        result = Orchestrator._check_false_completion(state)
        assert result is None

    def test_no_plan_returns_none(self, state: SessionState):
        state.plan = None
        result = Orchestrator._check_false_completion(state)
        assert result is None

    def test_counter_increments_on_each_reject(self, state: SessionState):
        state._pending_verifications.add("deploy.yml")
        Orchestrator._check_false_completion(state)
        assert state._false_completion_rejects == 1
        Orchestrator._check_false_completion(state)
        assert state._false_completion_rejects == 2
