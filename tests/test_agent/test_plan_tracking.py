"""Tests for plan step tracking and WIP=1 enforcement."""

from __future__ import annotations

import pytest

from ansible_forge.agent.orchestrator import Orchestrator, SessionState
from ansible_forge.workspace.manager import Workspace


@pytest.fixture
def state(tmp_path) -> SessionState:
    ws = Workspace(tmp_path, "test-session")
    return SessionState(session_id="test", workspace=ws)


class TestPlanStepTracking:
    def test_advance_marks_step_done(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "in_progress"},
                {"step": 2, "tool": "generate_playbook", "status": "pending"},
            ],
            "status": "planned",
        }
        Orchestrator._advance_plan_step(state, "web_search", succeeded=True)
        assert state.plan["steps"][0]["status"] == "done"
        assert state.plan["steps"][1]["status"] == "in_progress"

    def test_advance_marks_step_failed(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "in_progress"},
            ],
            "status": "planned",
        }
        Orchestrator._advance_plan_step(state, "web_search", succeeded=False)
        assert state.plan["steps"][0]["status"] == "failed"

    def test_wip_1_auto_advances_next(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "in_progress"},
                {"step": 2, "tool": "generate_playbook", "status": "pending"},
                {"step": 3, "tool": "execute_playbook", "status": "pending"},
            ],
            "status": "planned",
        }
        Orchestrator._advance_plan_step(state, "web_search", succeeded=True)
        wip_count = sum(
            1 for s in state.plan["steps"] if s["status"] == "in_progress"
        )
        assert wip_count == 1
        assert state.plan["steps"][1]["status"] == "in_progress"

    def test_no_plan_is_noop(self, state: SessionState):
        state.plan = None
        Orchestrator._advance_plan_step(state, "web_search", succeeded=True)

    def test_unmatched_tool_is_noop(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "in_progress"},
            ],
            "status": "planned",
        }
        Orchestrator._advance_plan_step(state, "generate_playbook", succeeded=True)
        assert state.plan["steps"][0]["status"] == "in_progress"

    def test_all_done_no_auto_advance(self, state: SessionState):
        state.plan = {
            "steps": [
                {"step": 1, "tool": "web_search", "status": "in_progress"},
            ],
            "status": "planned",
        }
        Orchestrator._advance_plan_step(state, "web_search", succeeded=True)
        assert state.plan["steps"][0]["status"] == "done"


class TestStateSnapshot:
    def test_build_and_restore_snapshot(self, state: SessionState):
        state.plan = {"steps": [{"step": 1, "status": "done"}], "status": "planned"}
        state._pending_verifications = {"deploy.yml"}
        state._approved_playbooks = {"site.yml"}
        state.step_count = 5

        snapshot = Orchestrator._build_state_snapshot(state)
        assert snapshot["plan"] == state.plan
        assert "deploy.yml" in snapshot["pending_verifications"]
        assert snapshot["step_count"] == 5

        new_state = SessionState(session_id="test2", workspace=state.workspace)
        Orchestrator._restore_state_snapshot(new_state, snapshot)
        assert new_state.plan == state.plan
        assert "deploy.yml" in new_state._pending_verifications
        assert new_state.step_count == 5
        assert "site.yml" in new_state._approved_playbooks

    def test_restore_handles_empty_data(self, state: SessionState):
        Orchestrator._restore_state_snapshot(state, {})
        assert state.plan is None
        assert state.step_count == 0

    def test_restore_handles_bad_types(self, state: SessionState):
        Orchestrator._restore_state_snapshot(state, {
            "plan": "not a dict",
            "pending_verifications": "not a list",
            "step_count": None,
            "approved_playbooks": 42,
        })
        assert state.plan is None
        assert len(state._pending_verifications) == 0
        assert state.step_count == 0
