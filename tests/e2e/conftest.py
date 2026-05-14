"""Shared fixtures for e2e tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from ansible_forge.config import Settings


@pytest.fixture
def e2e_settings(tmp_path: Path) -> Settings:
    """Settings for e2e testing with mock LLM."""
    return Settings(
        llm_provider="openai",
        llm_model="openai/gpt-4o-mini",
        default_project_dir=tmp_path / "projects",
        api_key="test-key-e2e",
        log_level="debug",
        session_timeout_seconds=60,
    )


@pytest.fixture
def e2e_workspace(tmp_path: Path) -> Path:
    """Create a workspace structure for e2e tests."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "inventory").mkdir()
    tuyere = ws / ".tuyere"
    tuyere.mkdir()
    for subdir in ("env", "artifacts", "ssh_keys"):
        (tuyere / subdir).mkdir()
    return ws


@pytest.fixture
def mock_llm_client():
    """Mock LLM client that returns scripted responses."""
    with patch("ansible_forge.agent.orchestrator.LLMClient") as mock_cls:
        instance = AsyncMock()
        mock_cls.return_value = instance
        yield instance
