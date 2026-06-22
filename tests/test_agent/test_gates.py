"""Tests for orchestrator gates: verify gate and false-completion guard."""

from __future__ import annotations

from types import SimpleNamespace
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


def _adhoc(module: str, args: str = "", check_mode: bool = False):
    return SimpleNamespace(
        name="run_adhoc",
        arguments={"module": module, "module_args": args, "check_mode": check_mode},
    )


class TestPlaybookFirstGate:
    _orch = SimpleNamespace(_is_diagnostic_adhoc=Orchestrator._is_diagnostic_adhoc)

    def test_blocks_mutating_adhoc_without_artifacts(self, state: SessionState):
        tc = _adhoc("ansible.builtin.shell", "oc apply -f manifest.yml")
        result = Orchestrator._check_playbook_first_gate(self._orch, state, tc)
        assert result is not None
        assert result.status == ToolStatus.ERROR
        assert "BLOCKED" in result.output

    def test_allows_mutating_adhoc_after_artifact_generated(self, state: SessionState):
        state._generated_artifacts.add("generate_playbook")
        tc = _adhoc("ansible.builtin.shell", "oc apply -f manifest.yml")
        result = Orchestrator._check_playbook_first_gate(self._orch, state, tc)
        assert result is None

    def test_allows_diagnostic_readonly_adhoc(self, state: SessionState):
        tc = _adhoc("ansible.builtin.ping")
        result = Orchestrator._check_playbook_first_gate(self._orch, state, tc)
        assert result is None

    def test_does_not_apply_to_non_adhoc_tools(self, state: SessionState):
        tc = SimpleNamespace(name="execute_playbook", arguments={})
        result = Orchestrator._check_playbook_first_gate(self._orch, state, tc)
        assert result is None


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


def _exec_error(error: str):
    return SimpleNamespace(error=error, data=None)


class TestAutoFixMissingDeps:
    """The missing-dependency auto-fix must target the EE in EE mode (not host)."""

    @pytest.mark.asyncio
    async def test_routes_to_ee_install_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import ansible_forge.tools.ee_runtime as ee

        monkeypatch.setattr(ee, "is_ee_enabled", lambda: True)
        captured: dict = {}

        async def fake_ee_pip(pkgs, ws, timeout=900):
            captured["pkgs"] = pkgs
            return True, "ok"

        monkeypatch.setattr(ee, "ee_pip_install", fake_ee_pip)

        ws = MagicMock()
        ws.path = tmp_path
        state = SessionState("s", ws)
        result = _exec_error("ModuleNotFoundError: No module named 'boto3'")

        fixed, pkg_list = await Orchestrator._auto_fix_missing_deps(
            SimpleNamespace(), state, "execute_playbook", result
        )
        assert fixed
        assert "boto3" in pkg_list
        assert captured["pkgs"] == ["boto3"]

    @pytest.mark.asyncio
    async def test_routes_to_host_install_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        import ansible_forge.dep_manager as dm
        import ansible_forge.tools.ee_runtime as ee

        monkeypatch.setattr(ee, "is_ee_enabled", lambda: False)
        captured: dict = {}

        async def fake_ensure(pkgs, reason=""):
            captured["pkgs"] = pkgs
            return True, "ok"

        monkeypatch.setattr(dm, "ensure_packages", fake_ensure)

        ws = MagicMock()
        ws.path = tmp_path
        state = SessionState("s", ws)
        result = _exec_error("ModuleNotFoundError: No module named 'kubernetes'")

        fixed, pkg_list = await Orchestrator._auto_fix_missing_deps(
            SimpleNamespace(), state, "execute_playbook", result
        )
        assert fixed
        assert captured["pkgs"] == ["kubernetes"]

    @pytest.mark.asyncio
    async def test_no_missing_module_returns_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ):
        ws = MagicMock()
        ws.path = tmp_path
        state = SessionState("s", ws)
        result = _exec_error("Connection refused")

        fixed, pkg_list = await Orchestrator._auto_fix_missing_deps(
            SimpleNamespace(), state, "execute_playbook", result
        )
        assert not fixed
        assert pkg_list == ""
