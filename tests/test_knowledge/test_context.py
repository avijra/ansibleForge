"""Tests for the knowledge context builder."""

from __future__ import annotations

from pathlib import Path

import pytest

from ansible_forge.knowledge.context import (
    _extract_mentions,
    build_knowledge_context,
)
from ansible_forge.knowledge.graph import KnowledgeGraph


@pytest.fixture()
def global_graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(tmp_path / "global.kuzu")


@pytest.fixture()
def project_graph(tmp_path: Path) -> KnowledgeGraph:
    return KnowledgeGraph(tmp_path / "project.kuzu")


class TestExtractMentions:
    def test_extracts_ip_addresses(self) -> None:
        msgs = [{"content": "Deploy to 192.168.1.10 and 10.0.0.5"}]
        hosts, _ = _extract_mentions(msgs)
        assert "192.168.1.10" in hosts
        assert "10.0.0.5" in hosts

    def test_extracts_module_fqcns(self) -> None:
        msgs = [{"content": "Use ansible.builtin.apt to install nginx"}]
        _, modules = _extract_mentions(msgs)
        assert "ansible.builtin.apt" in modules

    def test_ignores_0000(self) -> None:
        msgs = [{"content": "bind to 0.0.0.0"}]
        hosts, _ = _extract_mentions(msgs)
        assert "0.0.0.0" not in hosts

    def test_handles_empty_messages(self) -> None:
        hosts, modules = _extract_mentions([])
        assert len(hosts) == 0
        assert len(modules) == 0

    def test_only_scans_last_10(self) -> None:
        msgs = [{"content": f"host 10.0.0.{i}"} for i in range(20)]
        hosts, _ = _extract_mentions(msgs)
        assert "10.0.0.0" not in hosts
        assert "10.0.0.19" in hosts


class TestBuildContext:
    def test_empty_when_no_graphs(self) -> None:
        ctx = build_knowledge_context(None, None, [])
        assert ctx == ""

    def test_empty_when_no_relevant_data(
        self, global_graph: KnowledgeGraph, project_graph: KnowledgeGraph
    ) -> None:
        msgs = [{"content": "Hello world"}]
        ctx = build_knowledge_context(global_graph, project_graph, msgs)
        assert ctx == ""

    def test_includes_error_context_for_module(
        self, global_graph: KnowledgeGraph, project_graph: KnowledgeGraph
    ) -> None:
        global_graph.merge_error_pattern(
            "e1", "Package not found", module="ansible.builtin.apt",
            os_family="Debian", first_seen=100,
        )
        msgs = [{"content": "Use ansible.builtin.apt to install nginx"}]
        ctx = build_knowledge_context(global_graph, project_graph, msgs)
        assert "ansible.builtin.apt" in ctx
        assert "Package not found" in ctx

    def test_includes_host_history(
        self, global_graph: KnowledgeGraph, project_graph: KnowledgeGraph
    ) -> None:
        project_graph.merge_host("192.168.1.10", os_family="Debian", distribution="Ubuntu")
        project_graph.merge_task("t1", "Install nginx")
        project_graph.link_ran_task("192.168.1.10", "t1", "ok", 1000)

        msgs = [{"content": "Deploy to 192.168.1.10"}]
        ctx = build_knowledge_context(global_graph, project_graph, msgs)
        assert "192.168.1.10" in ctx
        assert "Install nginx" in ctx
        assert "ok" in ctx

    def test_includes_resolution_in_error_context(
        self, global_graph: KnowledgeGraph, project_graph: KnowledgeGraph
    ) -> None:
        global_graph.merge_error_pattern(
            "e1", "Service not found", module="ansible.builtin.service",
            os_family="Debian", first_seen=100,
        )
        global_graph.create_resolution(
            "r1", "Install package first", "apt install", True, 200
        )
        global_graph.link_resolution_resolves("r1", "e1")

        msgs = [{"content": "Use ansible.builtin.service to start nginx"}]
        ctx = build_knowledge_context(global_graph, project_graph, msgs)
        assert "Install package first" in ctx
        assert "fixed" in ctx
