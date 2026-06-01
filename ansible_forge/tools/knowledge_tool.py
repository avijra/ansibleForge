"""Tool for querying compiled knowledge packs and cross-project learning."""

from __future__ import annotations

from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)


class KnowledgeTool(BaseTool):
    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search compiled knowledge packs and cross-project learning store. "
            "Returns pre-compiled domain knowledge, past bug-fix patterns, and "
            "successful strategies from previous sessions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keywords to search for in knowledge packs",
                },
                "source": {
                    "type": "string",
                    "enum": ["all", "packs", "learning"],
                    "description": "'all' searches both, 'packs' searches knowledge packs only, 'learning' searches past bug fixes",
                },
                "record_pattern": {
                    "type": "object",
                    "description": "Record a successful pattern for future sessions",
                    "properties": {
                        "name": {"type": "string"},
                        "description": {"type": "string"},
                    },
                },
            },
            "required": ["keywords"],
        }

    async def execute(
        self,
        keywords: list[str],
        source: str = "all",
        record_pattern: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if record_pattern:
            return self._handle_record(record_pattern)

        results: list[str] = []

        if source in ("all", "packs"):
            try:
                from ansible_forge.knowledge.packs import PackRegistry
                workspace_path = kwargs.get("_workspace_path")
                registry = PackRegistry(workspace_path)
                pack_results = registry.query(keywords)
                if pack_results:
                    results.append("## Knowledge Packs\n")
                    for r in pack_results[:5]:
                        results.append(
                            f"### {r['title']} (pack: {r.get('pack', '?')})\n"
                            f"{r.get('summary', '')}\n\n{r.get('content', '')}\n"
                        )
            except Exception:
                logger.debug("knowledge_pack_search_failed", exc_info=True)

        if source in ("all", "learning"):
            try:
                from ansible_forge.knowledge.learning_store import LearningStore
                store = LearningStore.get_instance()
                learning_results = store.recall_all(keywords, limit=5)
                if learning_results:
                    results.append("## Past Experience\n")
                    for entry in learning_results:
                        if entry.get("type") == "bug_fix":
                            results.append(
                                f"- **Bug Fix** ({entry.get('tool', '?')}): "
                                f"error=`{entry.get('error_pattern', '')[:150]}` "
                                f"→ fix: {entry.get('fix', '')[:300]}\n"
                            )
                        else:
                            results.append(
                                f"- **Pattern**: {entry.get('name', '?')}: "
                                f"{entry.get('description', '')[:300]}\n"
                            )
            except Exception:
                logger.debug("learning_search_failed", exc_info=True)

        if not results:
            return ToolResult.success(
                "No matching knowledge found. Use web_search or search_docs instead.",
            )

        return ToolResult.success("\n".join(results))

    @staticmethod
    def _handle_record(pattern: dict[str, str]) -> ToolResult:
        name = pattern.get("name", "")
        desc = pattern.get("description", "")
        if not name or not desc:
            return ToolResult.fail("'name' and 'description' are required to record a pattern")
        try:
            from ansible_forge.knowledge.learning_store import LearningStore
            msg = LearningStore.get_instance().record_pattern(name, desc)
            return ToolResult.success(msg)
        except Exception as exc:
            return ToolResult.fail(f"Failed to record pattern: {exc}")
