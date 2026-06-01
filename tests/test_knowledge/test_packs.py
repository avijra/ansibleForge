"""Tests for the knowledge pack system."""

from __future__ import annotations

from pathlib import Path

from ansible_forge.knowledge.packs import (
    ConceptPage,
    KnowledgePack,
    PackRegistry,
    _parse_frontmatter,
)


class TestParseFrontmatter:
    def test_parses_yaml_frontmatter(self):
        text = "---\ntitle: Test Page\ntags: k8s, gpu\n---\nBody content here."
        meta, body = _parse_frontmatter(text)
        assert meta["title"] == "Test Page"
        assert meta["tags"] == "k8s, gpu"
        assert body == "Body content here."

    def test_no_frontmatter(self):
        text = "Just plain body text."
        meta, body = _parse_frontmatter(text)
        assert meta == {}
        assert body == text


class TestConceptPage:
    def test_loads_page_with_frontmatter(self, tmp_path: Path):
        page_file = tmp_path / "test-page.md"
        page_file.write_text(
            "---\ntitle: GPU Setup\nsummary: How to set up GPUs\ntags: gpu, nvidia\n---\n"
            "Install the driver first."
        )
        page = ConceptPage(page_file)
        assert page.title == "GPU Setup"
        assert page.summary == "How to set up GPUs"
        assert "gpu" in page.tags
        assert "nvidia" in page.tags
        assert "Install the driver" in page.body

    def test_loads_page_without_frontmatter(self, tmp_path: Path):
        page_file = tmp_path / "plain-page.md"
        page_file.write_text("Just content without frontmatter.")
        page = ConceptPage(page_file)
        assert page.title == "Plain Page"
        assert page.body == "Just content without frontmatter."


class TestKnowledgePack:
    def test_loads_pages_from_directory(self, tmp_path: Path):
        pack_dir = tmp_path / "test-pack"
        pack_dir.mkdir()
        (pack_dir / "page1.md").write_text(
            "---\ntitle: Page 1\ntags: ansible\n---\nContent 1"
        )
        (pack_dir / "page2.md").write_text(
            "---\ntitle: Page 2\ntags: terraform\n---\nContent 2"
        )
        (pack_dir / "_ignored.md").write_text("Should be skipped")

        pack = KnowledgePack(pack_dir)
        assert pack.page_count == 2

    def test_query_matches_tags(self, tmp_path: Path):
        pack_dir = tmp_path / "test-pack"
        pack_dir.mkdir()
        (pack_dir / "gpu.md").write_text(
            "---\ntitle: GPU Setup\ntags: gpu, nvidia, cuda\n---\n"
            "Install NVIDIA drivers."
        )
        (pack_dir / "network.md").write_text(
            "---\ntitle: Network Setup\ntags: vpc, subnet\n---\n"
            "Configure networking."
        )

        pack = KnowledgePack(pack_dir)
        results = pack.query(["gpu", "nvidia"])
        assert len(results) == 1
        assert results[0]["title"] == "GPU Setup"

    def test_query_empty_keywords(self, tmp_path: Path):
        pack_dir = tmp_path / "test-pack"
        pack_dir.mkdir()
        (pack_dir / "page.md").write_text("---\ntitle: Test\ntags: a\n---\nContent")
        pack = KnowledgePack(pack_dir)
        assert pack.query([]) == []


class TestPackRegistry:
    def test_loads_global_and_workspace_packs(self, tmp_path: Path):
        ws_knowledge = tmp_path / ".tuyere" / "knowledge" / "my-pack"
        ws_knowledge.mkdir(parents=True)
        (ws_knowledge / "page.md").write_text(
            "---\ntitle: WS Page\ntags: test\n---\nWS Content"
        )
        registry = PackRegistry(tmp_path)
        assert "my-pack" in registry.pack_names
        assert registry.total_pages == 1

    def test_query_across_packs(self, tmp_path: Path):
        ws_knowledge = tmp_path / ".tuyere" / "knowledge"
        pack1 = ws_knowledge / "pack1"
        pack1.mkdir(parents=True)
        (pack1 / "a.md").write_text("---\ntitle: A\ntags: ansible\n---\nAnsible stuff")
        pack2 = ws_knowledge / "pack2"
        pack2.mkdir(parents=True)
        (pack2 / "b.md").write_text("---\ntitle: B\ntags: ansible, roles\n---\nRoles stuff")

        registry = PackRegistry(tmp_path)
        results = registry.query(["ansible"])
        assert len(results) == 2

    def test_format_context_returns_empty_on_no_match(self, tmp_path: Path):
        registry = PackRegistry(tmp_path)
        assert registry.format_context(["nonexistent"]) == ""
