"""Shared test fixtures for AnsibleForge."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from ansible_forge.config import Settings
from ansible_forge.main import create_app


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary workspace with the new user-owned project layout.

    Playbooks, inventory, and roles live at the root.
    Runner internals live in ``.tuyere/``.
    """
    (tmp_path / "inventory").mkdir()
    tuyere = tmp_path / ".tuyere"
    tuyere.mkdir()
    for subdir in ("env", "artifacts", "ssh_keys"):
        (tuyere / subdir).mkdir()
    return tmp_path


@pytest.fixture
def sample_playbook() -> str:
    return (
        "---\n"
        "- name: Test play\n"
        "  hosts: localhost\n"
        "  connection: local\n"
        "  gather_facts: false\n"
        "  tasks:\n"
        "    - name: Say hello\n"
        "      ansible.builtin.debug:\n"
        "        msg: Hello from AnsibleForge\n"
    )


@pytest.fixture
def sample_inventory() -> str:
    return (
        "all:\n"
        "  hosts:\n"
        "    localhost:\n"
        "      ansible_connection: local\n"
    )


@pytest.fixture
def dangerous_playbook() -> str:
    return (
        "---\n"
        "- name: Dangerous play\n"
        "  hosts: all\n"
        "  become: true\n"
        "  tasks:\n"
        "    - name: Delete everything\n"
        "      ansible.builtin.shell: rm -rf /\n"
    )


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_provider="openai",
        llm_model="openai/gpt-4o-mini",
        default_project_dir=tmp_path / "projects",
        api_key="test-key-123",
        log_level="debug",
    )


@pytest_asyncio.fixture
async def async_client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
