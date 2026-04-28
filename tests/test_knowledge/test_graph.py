"""Tests for the KnowledgeGraph wrapper around KuzuDB."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.knowledge.graph import KnowledgeGraph


@pytest.fixture()
def graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(tmp_path / "test.kuzu")


class TestBootstrap:
    def test_creates_db_on_first_access(self, graph: KnowledgeGraph) -> None:
        assert graph.node_count("Host") == 0

    def test_idempotent_schema(self, tmp_path: Path) -> None:
        path = tmp_path / "idem.kuzu"
        g1 = KnowledgeGraph(path)
        g1.merge_host("h1")
        g1.close()

        g2 = KnowledgeGraph(path)
        assert g2.node_count("Host") == 1


class TestHostCRUD:
    def test_merge_creates_host(self, graph: KnowledgeGraph) -> None:
        graph.merge_host("web1", os_family="Debian", distribution="Ubuntu")
        assert graph.node_count("Host") == 1

    def test_merge_is_idempotent(self, graph: KnowledgeGraph) -> None:
        graph.merge_host("web1", os_family="Debian")
        graph.merge_host("web1", os_family="RedHat")
        assert graph.node_count("Host") == 1
        info = graph.query_host_info("web1")
        assert info[0][0] == "RedHat"

    def test_multiple_hosts(self, graph: KnowledgeGraph) -> None:
        graph.merge_host("web1")
        graph.merge_host("web2")
        assert graph.node_count("Host") == 2


class TestModuleCRUD:
    def test_merge_module(self, graph: KnowledgeGraph) -> None:
        graph.merge_module("ansible.builtin.apt", "Manage apt packages")
        assert graph.node_count("Module") == 1


class TestTaskAndEdges:
    def test_task_with_module_link(self, graph: KnowledgeGraph) -> None:
        graph.merge_task("t1", "Install nginx", module_fqcn="ansible.builtin.apt")
        graph.merge_module("ansible.builtin.apt")
        graph.link_uses_module("t1", "ansible.builtin.apt")
        assert graph.node_count("Task") == 1

    def test_host_ran_task(self, graph: KnowledgeGraph) -> None:
        graph.merge_host("web1")
        graph.merge_task("t1", "Install nginx")
        graph.link_ran_task("web1", "t1", "ok", 1000)
        history = graph.query_host_history("web1")
        assert len(history) == 1
        assert history[0][0] == "Install nginx"
        assert history[0][2] == "ok"


class TestErrorsAndResolutions:
    def test_error_pattern_and_query(self, graph: KnowledgeGraph) -> None:
        graph.merge_module("ansible.builtin.service")
        graph.merge_error_pattern(
            "abc123", "Could not find the requested service <HOST>",
            module="ansible.builtin.service", os_family="Debian", first_seen=100,
        )
        rows = graph.query_errors_for_module("ansible.builtin.service")
        assert len(rows) == 1
        assert "Could not find" in rows[0][0]

    def test_resolution_linked_to_error(self, graph: KnowledgeGraph) -> None:
        graph.merge_error_pattern("e1", "Package not found", module="apt")
        graph.create_resolution("r1", "Used apt update first", "apt update", True, 200)
        graph.link_resolution_resolves("r1", "e1")
        rows = graph.query_errors_for_module("apt")
        assert len(rows) == 1
        assert rows[0][2] == "Used apt update first"
        assert rows[0][3] is True


class TestExecution:
    def test_create_and_link_execution(self, graph: KnowledgeGraph) -> None:
        graph.merge_host("web1")
        graph.merge_playbook("deploy.yml")
        graph.create_execution("ex1", "sess1", 1000, "apply", "successful", 0)
        graph.link_execution_targets("ex1", "web1")
        graph.link_execution_runs("ex1", "deploy.yml")
        assert graph.node_count("Execution") == 1


class TestRecentErrors:
    def test_recent_errors_query(self, graph: KnowledgeGraph) -> None:
        graph.merge_error_pattern("e1", "Err A", module="mod_a", first_seen=100)
        graph.merge_error_pattern("e2", "Err B", module="mod_b", first_seen=200)
        rows = graph.query_recent_errors(limit=5)
        assert len(rows) == 2
