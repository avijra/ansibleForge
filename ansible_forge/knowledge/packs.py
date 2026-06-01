"""Compiled knowledge packs for domain-specific infrastructure guidance.

A knowledge pack is a directory of markdown concept pages with YAML
frontmatter containing title, summary, tags, and source references.
Packs are stored at ``~/.tuyere/knowledge/`` (global) or
``<workspace>/.tuyere/knowledge/`` (project-scoped) and queried by
keyword matching against tags and titles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_GLOBAL_PACKS_DIR = Path.home() / ".tuyere" / "knowledge"
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_MAX_CONTEXT_TOKENS = 8000
_CHARS_PER_TOKEN = 3


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip().lower()] = value.strip()
    return meta, text[match.end():]


class ConceptPage:
    __slots__ = ("path", "title", "summary", "tags", "body")

    def __init__(self, path: Path) -> None:
        self.path = path
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_frontmatter(raw)
        self.title = meta.get("title", path.stem.replace("-", " ").title())
        self.summary = meta.get("summary", "")
        tag_str = meta.get("tags", "")
        self.tags = [t.strip().lower() for t in tag_str.split(",") if t.strip()]
        self.body = body.strip()


class KnowledgePack:
    def __init__(self, pack_dir: Path) -> None:
        self.name = pack_dir.name
        self.path = pack_dir
        self._pages: list[ConceptPage] = []
        self._load()

    def _load(self) -> None:
        if not self.path.is_dir():
            return
        for md in sorted(self.path.glob("**/*.md")):
            if md.name.startswith("_"):
                continue
            try:
                self._pages.append(ConceptPage(md))
            except Exception:
                logger.debug("knowledge_page_load_error", path=str(md), exc_info=True)

    @property
    def page_count(self) -> int:
        return len(self._pages)

    def query(
        self, keywords: list[str], budget_chars: int | None = None,
    ) -> list[dict[str, Any]]:
        if not self._pages or not keywords:
            return []

        budget = budget_chars or (_MAX_CONTEXT_TOKENS * _CHARS_PER_TOKEN)
        lower_keywords = [k.lower() for k in keywords]

        scored: list[tuple[float, ConceptPage]] = []
        for page in self._pages:
            score = 0.0
            searchable = f"{page.title} {page.summary} {' '.join(page.tags)}".lower()
            for kw in lower_keywords:
                if kw in searchable:
                    score += 2.0
                if kw in page.body[:500].lower():
                    score += 1.0
            if score > 0:
                scored.append((score, page))

        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[dict[str, Any]] = []
        used_chars = 0
        for score, page in scored:
            entry_chars = len(page.body)
            if used_chars + entry_chars > budget:
                remaining = budget - used_chars
                if remaining > 200:
                    results.append({
                        "title": page.title,
                        "summary": page.summary,
                        "content": page.body[:remaining] + "\n[truncated]",
                        "source": str(page.path),
                        "score": score,
                    })
                break
            results.append({
                "title": page.title,
                "summary": page.summary,
                "content": page.body,
                "source": str(page.path),
                "score": score,
            })
            used_chars += entry_chars

        return results


class PackRegistry:
    def __init__(self, workspace_path: Path | None = None) -> None:
        self._packs: dict[str, KnowledgePack] = {}
        self._load_packs(workspace_path)

    def _load_packs(self, workspace_path: Path | None) -> None:
        search_dirs = [_GLOBAL_PACKS_DIR]
        if workspace_path:
            ws_knowledge = workspace_path / ".tuyere" / "knowledge"
            if ws_knowledge.is_dir():
                search_dirs.append(ws_knowledge)

        for base_dir in search_dirs:
            if not base_dir.is_dir():
                continue
            for entry in sorted(base_dir.iterdir()):
                if not entry.is_dir() or entry.name.startswith("."):
                    continue
                pack = KnowledgePack(entry)
                if pack.page_count > 0:
                    self._packs[pack.name] = pack
                    logger.info(
                        "knowledge_pack_loaded",
                        name=pack.name,
                        pages=pack.page_count,
                    )

    @property
    def pack_names(self) -> list[str]:
        return list(self._packs.keys())

    @property
    def total_pages(self) -> int:
        return sum(p.page_count for p in self._packs.values())

    def query(
        self, keywords: list[str], budget_chars: int | None = None,
    ) -> list[dict[str, Any]]:
        all_results: list[dict[str, Any]] = []
        for pack in self._packs.values():
            results = pack.query(keywords, budget_chars)
            for r in results:
                r["pack"] = pack.name
            all_results.extend(results)

        all_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return all_results

    def format_context(self, keywords: list[str]) -> str:
        results = self.query(keywords)
        if not results:
            return ""
        sections: list[str] = []
        for r in results[:5]:
            sections.append(
                f"### {r['title']} (pack: {r['pack']})\n"
                f"{r['summary']}\n\n{r['content']}"
            )
        return (
            "---\n"
            "KNOWLEDGE BASE (pre-compiled domain reference — trust this over training data):\n\n"
            + "\n\n".join(sections)
            + "\n---"
        )
