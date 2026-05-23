"""Web search tool for looking up Ansible documentation, examples, and troubleshooting."""

from __future__ import annotations

import contextlib
import html
import re
from typing import Any
from urllib.parse import quote_plus

import httpx

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

SEARCH_ENDPOINTS = {
    "duckduckgo": "https://html.duckduckgo.com/html/?q={query}",
}

ANSIBLE_DOCS_URLS = {
    "module": "https://docs.ansible.com/ansible/latest/collections/{fqcn_path}/index.html",
    "guide": "https://docs.ansible.com/ansible/latest/",
}


class WebSearcher(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web for Ansible documentation, troubleshooting guides, "
            "module usage examples, best practices, and solutions to errors. "
            "Use this when you encounter an error you cannot fix from local docs, "
            "need to find correct module parameters, or want to look up how others "
            "solved a similar problem. Searches DuckDuckGo and returns relevant results."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. Be specific. Good examples: "
                        "'ansible template module j2 file not found fix', "
                        "'ansible.builtin.get_url status_code 304 handling', "
                        "'ansible kubernetes deployment manifest example'"
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["ansible_docs", "general", "galaxy", "stackoverflow"],
                    "description": (
                        "Search scope: 'ansible_docs' adds site:docs.ansible.com, "
                        "'stackoverflow' adds site:stackoverflow.com, "
                        "'galaxy' adds site:galaxy.ansible.com, "
                        "'general' searches everywhere. Default: general"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default: 5, max: 10)",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": ["query"],
        }

    async def execute(
        self,
        query: str = "",
        scope: str = "general",
        max_results: int = 5,
        **kwargs: Any,
    ) -> ToolResult:
        if not query:
            return ToolResult.fail("query is required")

        scoped_query = self._apply_scope(query, scope)
        max_results = min(max_results, 10)

        try:
            results = await self._search_duckduckgo(scoped_query, max_results)
        except Exception as exc:
            logger.warning("web_search_failed", error=str(exc))
            return ToolResult.fail(f"Web search failed: {exc}")

        if not results:
            return ToolResult.ok(
                output=f"No results found for: {scoped_query}",
                results=[],
            )

        # Try to fetch content from the top result for more detail
        top_content = ""
        if results:
            with contextlib.suppress(Exception):
                top_content = await self._fetch_page_content(results[0]["url"])

        formatted = self._format_results(results, top_content)
        return ToolResult.ok(
            output=formatted,
            results=results,
            query=scoped_query,
        )

    @staticmethod
    def _apply_scope(query: str, scope: str) -> str:
        prefix = {
            "ansible_docs": "site:docs.ansible.com ansible",
            "stackoverflow": "site:stackoverflow.com ansible",
            "galaxy": "site:galaxy.ansible.com",
            "general": "ansible",
        }
        return f"{prefix.get(scope, 'ansible')} {query}"

    @staticmethod
    async def _search_duckduckgo(query: str, max_results: int) -> list[dict[str, str]]:
        url = SEARCH_ENDPOINTS["duckduckgo"].format(query=quote_plus(query))

        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={"User-Agent": "Tuyere/1.0 (Infrastructure automation agent)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        return _parse_duckduckgo_html(resp.text, max_results)

    @staticmethod
    async def _fetch_page_content(url: str) -> str:
        """Fetch a page and extract a text summary (first ~2000 chars of content)."""
        async with httpx.AsyncClient(
            timeout=10,
            follow_redirects=True,
            headers={"User-Agent": "Tuyere/1.0 (Infrastructure automation agent)"},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        text = _html_to_text(resp.text)
        return text[:3000] if text else ""

    @staticmethod
    def _format_results(results: list[dict[str, str]], top_content: str) -> str:
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")

        if top_content:
            lines.append("---")
            lines.append("**Top result content (excerpt):**")
            lines.append(top_content[:2000])

        return "\n".join(lines)


def _parse_duckduckgo_html(html_content: str, max_results: int) -> list[dict[str, str]]:
    """Parse search results from DuckDuckGo HTML response."""
    results: list[dict[str, str]] = []

    # Extract result blocks
    result_pattern = re.compile(
        r'<a\s+rel="nofollow"\s+class="result__a"\s+href="([^"]+)"[^>]*>(.*?)</a>'
        r'.*?<a\s+class="result__snippet"[^>]*>(.*?)</a>',
        re.DOTALL,
    )

    for match in result_pattern.finditer(html_content):
        if len(results) >= max_results:
            break

        url = html.unescape(match.group(1)).strip()
        title = _strip_html(match.group(2)).strip()
        snippet = _strip_html(match.group(3)).strip()

        if url and title:
            # DuckDuckGo wraps URLs in a redirect
            if "uddg=" in url:
                from urllib.parse import parse_qs, urlparse
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                url = qs.get("uddg", [url])[0]

            results.append({"title": title, "url": url, "snippet": snippet})

    # Fallback: simpler pattern if the above didn't match
    if not results:
        link_pattern = re.compile(
            r'<a[^>]+href="(https?://[^"]+)"[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        for match in link_pattern.finditer(html_content):
            if len(results) >= max_results:
                break
            url = html.unescape(match.group(1)).strip()
            title = _strip_html(match.group(2)).strip()
            if url and title and "duckduckgo" not in url:
                results.append({"title": title, "url": url, "snippet": ""})

    return results


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities."""
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean)


def _html_to_text(html_content: str) -> str:
    """Very basic HTML to text conversion for page content extraction."""
    # Remove script and style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    # Replace block elements with newlines
    text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode entities
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
