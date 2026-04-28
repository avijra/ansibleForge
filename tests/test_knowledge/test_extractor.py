"""Tests for the knowledge graph entity extractor."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.knowledge.extractor import (
    _error_hash,
    _sanitise_error,
    _task_id,
    ingest_tool_result,
)
from ansible_forge.knowledge.graph import KnowledgeGraph
from ansible_forge.tools.base import ToolResult, ToolStatus


@pytest.fixture()
def graphs(tmp_path: Path) -> tuple[KnowledgeGraph, KnowledgeGraph]:
    g = KnowledgeGraph(tmp_path / "global.kuzu")
    p = KnowledgeGraph(tmp_path / "project.kuzu")
    return g, p


class TestSanitise:
    def test_strips_ip_addresses(self) -> None:
        msg = "Failed to connect to 192.168.1.5 port 22"
        assert "<HOST>" in _sanitise_error(msg)
        assert "192.168.1.5" not in _sanitise_error(msg)

    def test_strips_paths(self) -> None:
        msg = "File not found: /tmp/ansible_xyz/foo.yml"
        assert "<PATH>" in _sanitise_error(msg)

    def test_truncates_long_messages(self) -> None:
        msg = "x" * 1000
        assert len(_sanitise_error(msg)) <= 500


class TestHashing:
    def test_error_hash_deterministic(self) -> None:
        h1 = _error_hash("some error", "ansible.builtin.apt")
        h2 = _error_hash("some error", "ansible.builtin.apt")
        assert h1 == h2

    def test_different_module_different_hash(self) -> None:
        h1 = _error_hash("some error", "ansible.builtin.apt")
        h2 = _error_hash("some error", "ansible.builtin.yum")
        assert h1 != h2

    def test_task_id_deterministic(self) -> None:
        assert _task_id("Install nginx", "web1") == _task_id("Install nginx", "web1")


class TestExecutorExtractor:
    def test_creates_host_task_execution(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Playbook executed successfully. 2 task event(s).",
            data={
                "summary": {"status": "successful", "rc": 0, "stats": {}, "event_count": 2},
                "events": [
                    {
                        "event": "runner_on_ok",
                        "host": "web1",
                        "task": "Install Apache",
                        "result": {"changed": True, "msg": "ok"},
                    },
                    {
                        "event": "runner_on_ok",
                        "host": "web1",
                        "task": "Start Apache",
                        "result": {"changed": False},
                    },
                ],
                "mode": "apply",
            },
        )
        ingest_tool_result("execute_playbook", result, "sess1", global_g, project_g)

        assert project_g.node_count("Host") == 1
        assert project_g.node_count("Task") == 2
        assert project_g.node_count("Execution") == 1

    def test_failed_task_creates_error_pattern(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.ERROR,
            output="",
            error="Playbook failed",
            data={
                "summary": {"status": "failed", "rc": 2, "stats": {}, "event_count": 1},
                "events": [
                    {
                        "event": "runner_on_failed",
                        "host": "db1",
                        "task": "Install MySQL",
                        "result": {
                            "changed": False,
                            "msg": "Could not find package mysql-server",
                            "module_fqcn": "ansible.builtin.apt",
                        },
                    },
                ],
                "mode": "apply",
            },
        )
        ingest_tool_result("execute_playbook", result, "sess1", global_g, project_g)

        assert global_g.node_count("ErrorPattern") == 1
        assert global_g.node_count("Module") == 1

    def test_resolution_created_when_task_succeeds_after_failure(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="ok",
            data={
                "summary": {"status": "successful", "rc": 0, "stats": {}, "event_count": 2},
                "events": [
                    {
                        "event": "runner_on_failed",
                        "host": "web1",
                        "task": "Install pkg",
                        "result": {"msg": "not found", "module_fqcn": "ansible.builtin.apt"},
                    },
                    {
                        "event": "runner_on_ok",
                        "host": "web1",
                        "task": "Install pkg",
                        "result": {"changed": True, "module_fqcn": "ansible.builtin.apt"},
                    },
                ],
                "mode": "apply",
            },
        )
        ingest_tool_result("execute_playbook", result, "sess1", global_g, project_g)
        assert global_g.node_count("Resolution") == 1


class TestFactsExtractor:
    def test_host_facts_merged(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Collected facts from 1 host(s).",
            data={
                "host_facts": {
                    "web1": {
                        "os_family": "Debian",
                        "distribution": "Ubuntu",
                        "distribution_version": "22.04",
                        "architecture": "x86_64",
                        "kernel": "5.15.0",
                    }
                }
            },
        )
        ingest_tool_result("collect_facts", result, "sess1", global_g, project_g)

        assert project_g.node_count("Host") == 1
        info = project_g.query_host_info("web1")
        assert info[0][0] == "Debian"
        assert info[0][1] == "Ubuntu"

        assert global_g.node_count("Host") == 1


class TestPlaybookExtractor:
    def test_playbook_created(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Playbook generated.",
            data={"path": "/tmp/ws/project/deploy.yml", "plays": 1},
        )
        ingest_tool_result("generate_playbook", result, "sess1", global_g, project_g)
        assert project_g.node_count("Playbook") == 1


class TestRoleExtractor:
    def test_role_created(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult(
            status=ToolStatus.SUCCESS,
            output="Role scaffolded.",
            data={"path": "/tmp/ws/project/roles/nginx", "directories": []},
        )
        ingest_tool_result("scaffold_role", result, "sess1", global_g, project_g)
        assert project_g.node_count("Role") == 1


class TestUnknownToolIsNoop:
    def test_unknown_tool_does_not_raise(
        self, graphs: tuple[KnowledgeGraph, KnowledgeGraph]
    ) -> None:
        global_g, project_g = graphs
        result = ToolResult.ok("done")
        ingest_tool_result("web_search", result, "sess1", global_g, project_g)
