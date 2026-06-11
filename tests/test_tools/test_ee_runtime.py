"""Tests for EE runtime and workspace sync helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from ansible_forge.tools import ee_runtime, workspace_sync


class TestWorkspaceSync:
    def test_remote_workspace_path_is_stable(self, tmp_path: Path) -> None:
        with patch(
            "ansible_forge.tools.workspace_sync.effective_ee_remote_workspace_root",
            return_value="/var/lib/tuyere/workspaces",
        ):
            first = workspace_sync.remote_workspace_path(tmp_path / "project")
            second = workspace_sync.remote_workspace_path(tmp_path / "project")
        assert first == second
        assert first.startswith("/var/lib/tuyere/workspaces/project-")

    def test_local_to_remote_path_preserves_relative_structure(self, tmp_path: Path) -> None:
        local_ws = tmp_path / "ws"
        nested = local_ws / "playbooks" / "site.yml"
        nested.parent.mkdir(parents=True)
        nested.write_text("---", encoding="utf-8")

        remote = workspace_sync.local_to_remote_path(
            nested,
            local_ws,
            "/var/lib/tuyere/workspaces/ws-abc",
        )
        assert remote.as_posix() == "/var/lib/tuyere/workspaces/ws-abc/playbooks/site.yml"

    def test_docker_host_url_normalizes_user_host(self) -> None:
        assert workspace_sync.docker_host_url("user@host") == "ssh://user@host"
        assert workspace_sync.docker_host_url("ssh://user@host") == "ssh://user@host"

    def test_normalize_ssh_host_strips_scheme(self) -> None:
        assert workspace_sync.normalize_ssh_host("ssh://user@host") == "user@host"


class TestEERuntimeHelpers:
    def test_docker_host_env_local_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: False)
        assert ee_runtime._docker_host_env() == {}

    def test_docker_host_env_remote_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: True)
        monkeypatch.setattr(
            ee_runtime,
            "effective_ee_remote_host",
            lambda: "runner@remote.example",
        )
        assert ee_runtime._docker_host_env() == {
            "DOCKER_HOST": "ssh://runner@remote.example"
        }

    def test_apply_ee_kwargs_sets_container_locale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        monkeypatch.setattr(ee_runtime, "get_container_runtime", lambda: "docker")
        monkeypatch.setattr(ee_runtime, "get_ee_image", lambda: "avijra28/tuyere-ee:latest")
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: False)
        kwargs = ee_runtime.apply_ee_kwargs(
            {
                "envvars": {
                    "LANG": "en_US.UTF-8",
                    "LC_ALL": "en_US.UTF-8",
                    "AWS_ACCESS_KEY_ID": "test",
                }
            },
            Path("/tmp/ws"),
        )
        assert kwargs["envvars"]["LANG"] == "C.UTF-8"
        assert kwargs["envvars"]["LC_ALL"] == "C.UTF-8"
        assert kwargs["envvars"]["AWS_ACCESS_KEY_ID"] == "test"

    def test_apply_ee_kwargs_sets_writable_home_and_ansible_tmp(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        monkeypatch.setattr(ee_runtime, "get_container_runtime", lambda: "docker")
        monkeypatch.setattr(ee_runtime, "get_ee_image", lambda: "avijra28/tuyere-ee:latest")
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: False)
        ws = tmp_path / "project"
        ws.mkdir()
        kwargs = ee_runtime.apply_ee_kwargs(
            {"envvars": {"HOME": "/"}},
            ws,
        )
        env = kwargs["envvars"]
        expected_home = str(ws / ".tuyere" / "ee-home")
        expected_tmp = str(ws / ".tuyere" / "tmp" / "ansible")
        assert env["HOME"] == expected_home
        assert env["TMPDIR"] == expected_tmp
        assert env["ANSIBLE_LOCAL_TMP"] == expected_tmp
        assert env["ANSIBLE_REMOTE_TMP"] == expected_tmp
        assert (ws / ".tuyere" / "ee-home" / ".ansible" / "tmp").is_dir()
        assert (ws / ".tuyere" / "tmp" / "ansible").is_dir()

    def test_apply_ee_kwargs_remote_uses_remote_workspace_paths(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        monkeypatch.setattr(ee_runtime, "get_container_runtime", lambda: "docker")
        monkeypatch.setattr(ee_runtime, "get_ee_image", lambda: "avijra28/tuyere-ee:latest")
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: True)
        monkeypatch.setattr(
            ee_runtime,
            "effective_ee_remote_host",
            lambda: "runner@remote.example",
        )
        ws = tmp_path / "project"
        ws.mkdir()
        remote_ws = "/var/lib/tuyere/workspaces/project-deadbeef"
        kwargs = ee_runtime.apply_ee_kwargs({"envvars": {}}, ws, remote_ws=remote_ws)
        env = kwargs["envvars"]
        assert env["HOME"] == f"{remote_ws}/.tuyere/ee-home"
        assert env["ANSIBLE_LOCAL_TMP"] == f"{remote_ws}/.tuyere/tmp/ansible"
        assert (ws / ".tuyere" / "ee-home" / ".ansible" / "tmp").is_dir()

    def test_build_volume_mounts_remote_only_workspace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(ee_runtime, "is_remote_mode", lambda: True)
        mounts = ee_runtime.build_volume_mounts(
            Path("/Users/me/project"),
            remote_ws="/var/lib/tuyere/workspaces/project-deadbeef",
        )
        assert mounts == ["/var/lib/tuyere/workspaces/project-deadbeef:/var/lib/tuyere/workspaces/project-deadbeef:Z"]

    @pytest.mark.asyncio
    async def test_schedule_pull_sets_ready_when_image_exists(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        ee_runtime._set_pull_state("idle", "")
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        monkeypatch.setattr(
            ee_runtime,
            "ee_image_available",
            AsyncMock(return_value=(True, "avijra28/tuyere-ee:latest")),
        )
        monkeypatch.setattr(
            ee_runtime,
            "verify_ee_ansible",
            AsyncMock(return_value=(True, "ansible [core 2.17.0]")),
        )

        ee_runtime.schedule_ee_image_pull()
        await ee_runtime._pull_task

        state = ee_runtime.get_pull_state()
        assert state["status"] == "ready"
        assert state["image_ready"] is True


class TestExecutionSettingsEndpoints:
    @pytest.mark.asyncio
    async def test_get_execution_settings_response_shape(
        self,
        async_client: AsyncClient,
    ) -> None:
        response = await async_client.get("/api/v1/settings/execution")
        assert response.status_code == 200
        data = response.json()
        assert set(data.keys()) >= {
            "enabled",
            "image",
            "container_runtime",
            "runtime_available",
            "host_mode",
            "remote_host",
            "remote_workspace_root",
            "image_ready",
            "image_pull_status",
            "image_pull_message",
            "source",
        }
        assert data["image_pull_status"] in ("idle", "pulling", "ready", "failed")

    @pytest.mark.asyncio
    async def test_enable_execution_schedules_pull(
        self,
        async_client: AsyncClient,
    ) -> None:
        scheduled = {"called": False}

        def _schedule() -> None:
            scheduled["called"] = True

        with patch("ansible_forge.tools.ee_runtime.schedule_ee_image_pull", _schedule):
            response = await async_client.put(
                "/api/v1/settings/execution",
                json={"enabled": True},
            )
        assert response.status_code == 200
        assert scheduled["called"] is True

        await async_client.delete("/api/v1/settings/execution")

    @pytest.mark.asyncio
    async def test_pull_endpoint_exists(self, async_client: AsyncClient) -> None:
        with patch(
            "ansible_forge.tools.ee_runtime.schedule_ee_image_pull",
            lambda: None,
        ):
            await async_client.put("/api/v1/settings/execution", json={"enabled": True})
            response = await async_client.post("/api/v1/settings/execution/pull")
        assert response.status_code == 200
        assert "image_pull_status" in response.json()
        await async_client.delete("/api/v1/settings/execution")
