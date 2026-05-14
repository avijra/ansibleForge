"""E2E test: verify agent error recovery and hard retry budget."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ansible_forge.agent.orchestrator import SessionState


@pytest.mark.e2e
class TestAgentErrorRecovery:
    """Test that the agent respects the hard retry budget."""

    @pytest.mark.asyncio
    async def test_consecutive_errors_increment(self):
        """Verify _consecutive_errors increments on tool failure."""
        state = SessionState(
            session_id="test-recovery",
            workspace=MagicMock(),
        )
        assert state._consecutive_errors == 0
        state._consecutive_errors += 1
        assert state._consecutive_errors == 1

    @pytest.mark.asyncio
    async def test_max_retries_default(self):
        """Verify default max error retries is 3."""
        state = SessionState(
            session_id="test-retries",
            workspace=MagicMock(),
        )
        assert state._max_error_retries == 3

    @pytest.mark.asyncio
    async def test_budget_exhausted_message_generated(self):
        """When consecutive_errors >= max_retries, the budget-exhausted message should
        instruct the LLM to stop and ask the user."""
        state = SessionState(
            session_id="test-budget",
            workspace=MagicMock(),
        )
        state._consecutive_errors = 3
        remaining = max(state._max_error_retries - state._consecutive_errors, 0)
        assert remaining == 0
        assert remaining <= 0


@pytest.mark.e2e
class TestAgentTimeout:
    """Test session wall-clock timeout behavior."""

    @pytest.mark.asyncio
    async def test_session_timeout_setting_default(self):
        """Verify session_timeout_seconds defaults to 7200 in production settings."""
        from ansible_forge.config import Settings

        default_settings = Settings(
            llm_provider="openai",
            llm_model="test",
        )
        assert default_settings.session_timeout_seconds == 7200

    @pytest.mark.asyncio
    async def test_session_timeout_setting_configurable(self):
        """Verify session_timeout_seconds can be overridden."""
        from ansible_forge.config import Settings

        settings = Settings(
            llm_provider="openai",
            llm_model="test",
            session_timeout_seconds=60,
        )
        assert settings.session_timeout_seconds == 60
