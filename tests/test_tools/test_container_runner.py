"""Tests for container-native Ansible execution used in remote EE mode."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from ansible_forge.tools import container_runner

_JSON_BLOB = json.dumps(
    {
        "plays": [
            {
                "tasks": [
                    {
                        "task": {"name": "ping"},
                        "hosts": {"web1": {"changed": False, "ping": "pong"}},
                    }
                ]
            }
        ],
        "stats": {"web1": {"ok": 1, "changed": 0, "failures": 0}},
    }
)


class TestComposeStdout:
    def test_keeps_clean_json_when_present(self) -> None:
        assert container_runner._compose_stdout(_JSON_BLOB, "WARNING: x") == _JSON_BLOB

    def test_appends_stderr_when_no_json(self) -> None:
        out = container_runner._compose_stdout("", "ERROR! bad playbook")
        assert "ERROR! bad playbook" in out


class TestContainerRunResult:
    def test_status_and_stats_from_json(self) -> None:
        result = container_runner.ContainerRunResult(0, _JSON_BLOB)
        assert result.status == "successful"
        assert result.rc == 0
        assert result.stats == {"web1": {"ok": 1, "changed": 0, "failures": 0}}

    def test_failure_status(self) -> None:
        result = container_runner.ContainerRunResult(2, "ERROR! boom")
        assert result.status == "failed"
        assert result.stats == {}


class TestTranslatePaths:
    def test_noop_in_local_mode(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setattr(container_runner, "is_remote_mode", lambda: False, raising=False)
        from ansible_forge.tools import ee_runtime

        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: False)
        extravars = {"key_file": str(tmp_path / "k")}
        assert container_runner._translate_paths(extravars, tmp_path) == extravars

    def test_translates_workspace_paths_in_remote_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from ansible_forge.tools import ee_runtime

        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: True)
        from ansible_forge.tools import workspace_sync

        monkeypatch.setattr(
            workspace_sync, "remote_workspace_path", lambda _ws: "/remote/ws"
        )
        key_path = tmp_path / "ssh_keys" / "id_rsa"
        key_path.parent.mkdir(parents=True)
        key_path.write_text("k", encoding="utf-8")
        out = container_runner._translate_paths(
            {"ansible_ssh_private_key_file": str(key_path), "region": "us"}, tmp_path
        )
        assert out["ansible_ssh_private_key_file"] == "/remote/ws/ssh_keys/id_rsa"
        assert out["region"] == "us"


class TestRunPlaybookInContainer:
    @pytest.mark.asyncio
    async def test_builds_argv_and_parses_events(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: dict[str, Any] = {}

        async def fake_ee_exec(cmd, cwd=None, env=None, ws=None, timeout=300, **_kw):
            captured["cmd"] = cmd
            captured["env"] = env
            return 0, _JSON_BLOB, ""

        from ansible_forge.tools import ee_runtime

        monkeypatch.setattr(ee_runtime, "ee_exec", fake_ee_exec)
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: False)

        result = await container_runner.run_playbook_in_container(
            ws=tmp_path,
            playbook="site.yml",
            inventory="inventory/hosts.yml",
            cmdline_args=["--check", "--diff"],
            extravars={"region": "us-east-1"},
            envvars={"AWS_REGION": "us-east-1"},
            verbosity=2,
            timeout=900,
        )

        cmd = captured["cmd"]
        assert cmd[0] == "ansible-playbook"
        assert "site.yml" in cmd
        assert "-i" in cmd and "inventory/hosts.yml" in cmd
        assert "-vv" in cmd
        assert "--check" in cmd and "--diff" in cmd
        assert any(c.startswith("@") and "extravars-" in c for c in cmd)
        assert captured["env"]["ANSIBLE_STDOUT_CALLBACK"] == "json"
        assert captured["env"]["AWS_REGION"] == "us-east-1"

        from ansible_forge.tools.executor import get_runner_events

        events = get_runner_events(result)
        assert any(e.get("event") == "runner_on_ok" for e in events)

        # extravars temp file is cleaned up
        leftover = list((tmp_path / ".tuyere" / "tmp").glob("extravars-*.json"))
        assert leftover == []
