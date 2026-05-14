"""E2E test: verify ansible-playbook can execute a localhost playbook.

This is an integration-level test that requires ansible-playbook on PATH.
It validates the full execution path from Python through ansible-runner.
"""

from __future__ import annotations

import shutil

import pytest


@pytest.mark.e2e
@pytest.mark.skipif(
    not shutil.which("ansible-playbook"),
    reason="ansible-playbook not found on PATH",
)
class TestLocalhostPlaybook:
    """Test that a simple localhost playbook can execute."""

    @pytest.mark.asyncio
    async def test_debug_playbook_succeeds(self, tmp_path):
        """A minimal debug playbook should execute without errors."""
        import asyncio

        playbook = tmp_path / "test.yml"
        playbook.write_text(
            "---\n"
            "- name: E2E test\n"
            "  hosts: localhost\n"
            "  connection: local\n"
            "  gather_facts: false\n"
            "  tasks:\n"
            "    - name: Write marker\n"
            "      ansible.builtin.copy:\n"
            "        content: e2e_success\n"
            "        dest: " + str(tmp_path / "marker.txt") + "\n"
        )

        inventory = tmp_path / "inventory.yml"
        inventory.write_text(
            "all:\n"
            "  hosts:\n"
            "    localhost:\n"
            "      ansible_connection: local\n"
        )

        import os

        env = os.environ.copy()
        env["ANSIBLE_FORCE_COLOR"] = "0"
        env["ANSIBLE_HOST_KEY_CHECKING"] = "False"
        env["ANSIBLE_LOCAL_TMP"] = str(tmp_path / ".ansible-tmp")
        env["ANSIBLE_REMOTE_TMP"] = str(tmp_path / ".ansible-tmp")

        proc = await asyncio.create_subprocess_exec(
            "ansible-playbook",
            str(playbook),
            "-i", str(inventory),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
        assert proc.returncode == 0, f"Playbook failed:\n{stderr.decode()}\n{stdout.decode()}"

        marker = tmp_path / "marker.txt"
        assert marker.exists()
        assert marker.read_text().strip() == "e2e_success"
