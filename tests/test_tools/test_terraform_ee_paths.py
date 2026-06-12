"""Regression tests for Terraform tools running inside the EE."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from ansible_forge.tools import ee_runtime, terraform_executor, terraform_inventory
from ansible_forge.tools.base import ToolStatus
from ansible_forge.tools.terraform_executor import TerraformExecutor
from ansible_forge.tools.terraform_inventory import TerraformInventoryBridge


@pytest.mark.asyncio
async def test_find_terraform_uses_container_binary_in_ee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = TerraformExecutor()
    resolver = AsyncMock(return_value="/tmp/terraform")
    monkeypatch.setattr(terraform_executor, "resolve_terraform_or_download_async", resolver)
    monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)

    tf_binary = await tool._find_terraform()

    assert tf_binary == "tofu"
    resolver.assert_not_awaited()


@pytest.mark.asyncio
async def test_find_terraform_uses_host_resolver_outside_ee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool = TerraformExecutor()
    resolver = AsyncMock(return_value="/tmp/tofu")
    monkeypatch.setattr(terraform_executor, "resolve_terraform_or_download_async", resolver)
    monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: False)

    tf_binary = await tool._find_terraform()

    assert tf_binary == "/tmp/tofu"
    resolver.assert_awaited_once()


@pytest.mark.asyncio
async def test_terraform_inventory_uses_ee_tofu_without_host_download(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ws = tmp_path / "workspace"
    tf_dir = ws / "terraform"
    tf_dir.mkdir(parents=True)

    resolver = AsyncMock(return_value="/tmp/tofu")
    monkeypatch.setattr(terraform_inventory, "resolve_terraform_or_download_async", resolver)
    monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)

    calls: list[list[str]] = []

    async def _fake_ee_exec(
        cmd: list[str],
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        timeout: int = 0,
        ws: Path | None = None,
    ) -> tuple[int, str, str]:
        calls.append(cmd)
        if cmd[:3] == ["tofu", "show", "-no-color"]:
            return (
                0,
                json.dumps(
                    {
                        "values": {
                            "root_module": {
                                "resources": [
                                    {
                                        "type": "aws_instance",
                                        "name": "web",
                                        "values": {
                                            "id": "i-12345",
                                            "public_ip": "203.0.113.10",
                                            "private_ip": "10.0.1.10",
                                            "tags": {"Name": "web-1"},
                                        },
                                    }
                                ]
                            }
                        }
                    }
                ),
                "",
            )
        return 1, "", "unexpected command"

    monkeypatch.setattr(ee_runtime, "ee_exec", _fake_ee_exec)

    class _DummyStore:
        def upsert_host(self, **kwargs: object) -> None:
            return None

    class _DummyInfrastructureStore:
        @staticmethod
        def get_instance() -> _DummyStore:
            return _DummyStore()

    monkeypatch.setattr(terraform_inventory, "InfrastructureStore", _DummyInfrastructureStore)

    tool = TerraformInventoryBridge()
    result = await tool.execute(workspace_path=str(ws))

    assert result.status == ToolStatus.SUCCESS
    assert calls
    assert calls[0][0] == "tofu"
    resolver.assert_not_awaited()
