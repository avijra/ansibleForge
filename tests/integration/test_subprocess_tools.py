"""Integration tests for subprocess-based tools.

These tests verify that the bundled/system Ansible CLI tools are reachable
and functional when invoked the same way the agent invokes them at runtime.
"""

from __future__ import annotations

import asyncio
import shutil

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        shutil.which("ansible-galaxy") is None,
        reason="ansible-galaxy not on PATH",
    ),
]


@pytest.mark.asyncio
async def test_galaxy_version() -> None:
    """ansible-galaxy --version must succeed."""
    proc = await asyncio.create_subprocess_exec(
        "ansible-galaxy", "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    assert proc.returncode == 0, f"ansible-galaxy --version failed: {stderr.decode()}"
    assert b"ansible" in stdout.lower()


@pytest.mark.asyncio
async def test_galaxy_list() -> None:
    """ansible-galaxy collection list should not produce SSL errors."""
    proc = await asyncio.create_subprocess_exec(
        "ansible-galaxy", "collection", "list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    combined = (stdout + stderr).decode()
    assert "CERTIFICATE_VERIFY_FAILED" not in combined, (
        f"SSL certificate error detected: {combined}"
    )


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ansible-vault") is None,
    reason="ansible-vault not on PATH",
)
async def test_vault_version() -> None:
    """ansible-vault --version must succeed."""
    proc = await asyncio.create_subprocess_exec(
        "ansible-vault", "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    assert proc.returncode == 0, f"ansible-vault --version failed: {stderr.decode()}"


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ansible-doc") is None,
    reason="ansible-doc not on PATH",
)
async def test_doc_searcher_builtin_copy() -> None:
    """ansible-doc can retrieve docs for ansible.builtin.copy."""
    proc = await asyncio.create_subprocess_exec(
        "ansible-doc", "ansible.builtin.copy",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
    assert proc.returncode == 0, f"ansible-doc failed: {stderr.decode()}"
    assert b"copy" in stdout.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ansible-lint") is None,
    reason="ansible-lint not on PATH",
)
async def test_lint_runner_version() -> None:
    """ansible-lint --version must succeed."""
    proc = await asyncio.create_subprocess_exec(
        "ansible-lint", "--version",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    assert proc.returncode == 0, f"ansible-lint --version failed: {stderr.decode()}"


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ansible-inventory") is None,
    reason="ansible-inventory not on PATH",
)
async def test_inventory_parse(tmp_path) -> None:
    """ansible-inventory can parse a basic static inventory."""
    inv_file = tmp_path / "hosts.ini"
    inv_file.write_text("[web]\nlocalhost ansible_connection=local\n")

    proc = await asyncio.create_subprocess_exec(
        "ansible-inventory", "-i", str(inv_file), "--list",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    assert proc.returncode == 0, f"ansible-inventory failed: {stderr.decode()}"
    assert b"web" in stdout
