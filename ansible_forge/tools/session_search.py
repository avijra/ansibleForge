from __future__ import annotations

from typing import Any

from ansible_forge.tools.base import BaseTool, ToolResult


class SessionSearchTool(BaseTool):
    @property
    def name(self) -> str:
        return "session_search"

    @property
    def description(self) -> str:
        return (
            "Search past session conversations. Use this when the user asks "
            "'remember when we...', 'what did we do about...', or when you need "
            "to recall configuration decisions, playbook patterns, or debugging "
            "context from previous sessions."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query — describe what you're looking for.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 5).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        from ansible_forge.persistence.session_store import SessionStore

        query = kwargs.get("query", "")
        limit = kwargs.get("limit", 5)
        if not query:
            return ToolResult.fail("'query' is required.")

        try:
            store = SessionStore()
            results = store.search_events(query, limit=limit)
        except Exception as exc:
            return ToolResult.fail(f"Session search failed: {exc}")

        if not results:
            return ToolResult.ok("No matching sessions found.")

        lines = []
        seen_sessions: set[str] = set()
        for r in results:
            sid = r["session_id"]
            if sid not in seen_sessions:
                seen_sessions.add(sid)
                lines.append(
                    f"### {r['session_title']} ({r['session_date']})"
                )
            excerpt = r.get("excerpt", "")
            if excerpt:
                lines.append(f"  [{r['event_type']}] {excerpt}")

        return ToolResult.ok("\n".join(lines), results=results)
