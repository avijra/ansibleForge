"""Regression tests: host Python interpreter must never leak into EE containers."""

from __future__ import annotations

import pytest

from ansible_forge.tools import (
    adhoc_runner,
    connectivity_tester,
    ee_runtime,
    executor,
    facts_collector,
)


@pytest.fixture
def _host_interp(monkeypatch: pytest.MonkeyPatch) -> str:
    interp = "/Users/me/.ansibleforge/python/cpython-3.12/bin/python3"
    monkeypatch.setattr(executor, "_resolve_python_interpreter", lambda: interp)
    monkeypatch.setattr(adhoc_runner, "_resolve_python_interpreter", lambda: interp)
    monkeypatch.setattr(connectivity_tester, "_resolve_python_interpreter", lambda: interp)
    monkeypatch.setattr(facts_collector, "_resolve_python_interpreter", lambda: interp)
    return interp


class TestEnvvarsRespectEEMode:
    def test_runner_envvars_skip_interpreter_in_ee(
        self, monkeypatch: pytest.MonkeyPatch, _host_interp: str,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        assert "ANSIBLE_PYTHON_INTERPRETER" not in executor._runner_envvars()
        assert "ANSIBLE_PYTHON_INTERPRETER" not in adhoc_runner._adhoc_envvars()
        assert "ANSIBLE_PYTHON_INTERPRETER" not in connectivity_tester._connectivity_envvars()
        assert "ANSIBLE_PYTHON_INTERPRETER" not in facts_collector._facts_envvars()

    def test_runner_envvars_include_interpreter_outside_ee(
        self, monkeypatch: pytest.MonkeyPatch, _host_interp: str,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: False)
        assert executor._runner_envvars()["ANSIBLE_PYTHON_INTERPRETER"] == _host_interp
        assert adhoc_runner._adhoc_envvars()["ANSIBLE_PYTHON_INTERPRETER"] == _host_interp


class TestLocalhostInventoryRespectsEEMode:
    def test_adhoc_localhost_inventory_omits_interpreter_in_ee(
        self, monkeypatch: pytest.MonkeyPatch, _host_interp: str,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        content = adhoc_runner._localhost_inventory_content()
        assert "ansible_python_interpreter" not in content
        assert "localhost ansible_connection=local" in content

    def test_adhoc_localhost_inventory_includes_interpreter_outside_ee(
        self, monkeypatch: pytest.MonkeyPatch, _host_interp: str,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: False)
        content = adhoc_runner._localhost_inventory_content()
        assert f"ansible_python_interpreter={_host_interp}" in content


class TestExecutorInterpreterInjection:
    def test_inject_python_interpreter_noop_in_ee(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _host_interp: str,
        tmp_path,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: True)
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "site.yml").write_text("- hosts: localhost\n", encoding="utf-8")
        merged: dict = {}
        executor._inject_python_interpreter(ws, "site.yml", merged)
        assert "ansible_python_interpreter" not in merged

    def test_inject_python_interpreter_applies_outside_ee(
        self,
        monkeypatch: pytest.MonkeyPatch,
        _host_interp: str,
        tmp_path,
    ) -> None:
        monkeypatch.setattr(ee_runtime, "is_ee_enabled", lambda: False)
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "site.yml").write_text("- hosts: localhost\n", encoding="utf-8")
        merged: dict = {}
        executor._inject_python_interpreter(ws, "site.yml", merged)
        assert merged["ansible_python_interpreter"] == _host_interp
