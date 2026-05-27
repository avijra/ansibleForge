"""Web search and documentation reading tool for infrastructure automation."""

from __future__ import annotations

import contextlib
import html
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

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

_DOCS_DOMAINS = frozenset({
    "docs.redhat.com", "docs.openshift.com", "access.redhat.com",
    "kubernetes.io", "registry.terraform.io",
    "docs.aws.amazon.com", "docs.ansible.com",
    "learn.microsoft.com", "cloud.google.com",
    "helm.sh", "artifacthub.io",
    "docs.docker.com", "docs.github.com",
    "grafana.com", "prometheus.io",
})

_DEEP_CONTENT_LIMIT = 12000
_DEFAULT_CONTENT_LIMIT = 5000


def _is_docs_domain(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith(f".{d}") for d in _DOCS_DOMAINS)
    except Exception:
        return False


class WebSearcher(BaseTool):
    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web or read a specific URL. Two modes:\n"
            "1. SEARCH mode (default): provide `query` to search DuckDuckGo. "
            "Returns result titles, URLs, and content from top results.\n"
            "2. READ mode: provide `url` to fetch and read a specific page. "
            "Use this to read official documentation, prerequisites pages, "
            "or any URL found in previous search results. Returns up to "
            "12000 chars from documentation sites.\n"
            "Always READ the official docs after finding them via search — "
            "search snippets are not enough for extracting prerequisites."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Search query. Be specific. Examples: "
                        "'Red Hat OpenShift AI MaaS prerequisites', "
                        "'terraform aws_eks_cluster required arguments', "
                        "'kubernetes GPU operator installation guide'"
                    ),
                },
                "url": {
                    "type": "string",
                    "description": (
                        "Fetch a specific URL directly instead of searching. "
                        "Use this to read documentation pages, prerequisites "
                        "pages, or any URL found in previous search results. "
                        "Returns full page content (up to 12000 chars for "
                        "documentation sites)."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["ansible_docs", "general", "galaxy", "stackoverflow"],
                    "description": (
                        "Search scope: 'ansible_docs' adds site:docs.ansible.com, "
                        "'stackoverflow' adds site:stackoverflow.com, "
                        "'galaxy' adds site:galaxy.ansible.com, "
                        "'general' searches everywhere (default)"
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results to return (default: 5, max: 10)",
                    "minimum": 1,
                    "maximum": 10,
                },
            },
            "required": [],
        }

    async def execute(
        self,
        query: str = "",
        url: str = "",
        scope: str = "general",
        max_results: int = 5,
        **kwargs: Any,
    ) -> ToolResult:
        if url:
            return await self._fetch_url_direct(url)

        if not query:
            return ToolResult.fail("Provide either `query` (to search) or `url` (to read a page)")

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

        fetched_contents: list[tuple[str, str]] = []
        for r in results[:2]:
            with contextlib.suppress(Exception):
                content = await self._fetch_page_content(r["url"])
                if content:
                    fetched_contents.append((r["url"], content))

        formatted = self._format_results(results, fetched_contents)
        return ToolResult.ok(
            output=formatted,
            results=results,
            query=scoped_query,
        )

    async def _fetch_url_direct(self, url: str) -> ToolResult:
        try:
            content = await self._fetch_page_content(url, deep=True)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("url_fetch_http_error", url=url, status=status)
            parent = _parent_url(url)
            hint = (
                f"The page returned HTTP {status}. This often means the URL "
                "has a wrong version number, moved, or the path is incorrect."
            )
            if parent:
                hint += (
                    f"\n\nTry the parent page: `web_search url={parent}`"
                    "\nOr search for the correct URL: "
                    "`web_search query=\"<product name> <topic> documentation\"`"
                )
            else:
                hint += (
                    "\nSearch for the correct URL: "
                    "`web_search query=\"<product name> <topic> documentation\"`"
                )
            return ToolResult.fail(hint)
        except Exception as exc:
            logger.warning("url_fetch_failed", url=url, error=str(exc))
            return ToolResult.fail(
                f"Could not fetch content from {url}: {exc}\n"
                "Try searching for the correct URL instead: "
                "`web_search query=\"<topic> official documentation\"`"
            )
        if not content:
            return ToolResult.fail(
                f"No readable content extracted from: {url}\n"
                "The page may require JavaScript or authentication. "
                "Try searching for an alternative source."
            )
        return ToolResult.ok(
            output=f"**Page content from {url}:**\n\n{content}",
            url=url,
        )

    @staticmethod
    def _apply_scope(query: str, scope: str) -> str:
        prefix = {
            "ansible_docs": "site:docs.ansible.com ansible",
            "stackoverflow": "site:stackoverflow.com",
            "galaxy": "site:galaxy.ansible.com",
            "general": "",
        }
        p = prefix.get(scope, "")
        return f"{p} {query}".strip() if p else query

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
    async def _fetch_page_content(url: str, deep: bool = False) -> str:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/125.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        text = _html_to_text(resp.text)
        if not text:
            return ""

        if deep:
            limit = _DEEP_CONTENT_LIMIT if _is_docs_domain(url) else 6000
        else:
            limit = _DEEP_CONTENT_LIMIT if _is_docs_domain(url) else _DEFAULT_CONTENT_LIMIT
        return text[:limit]

    @staticmethod
    def _format_results(
        results: list[dict[str, str]],
        fetched_contents: list[tuple[str, str]],
    ) -> str:
        lines = [f"Found {len(results)} result(s):\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. **{r['title']}**")
            lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet']}")
            lines.append("")

        for fetch_url, content in fetched_contents:
            lines.append("---")
            lines.append(f"**Content from {fetch_url}:**")
            lines.append(content[:4000])
            lines.append("")

        return "\n".join(lines)


def _parent_url(url: str) -> str | None:
    """Return the parent path of a URL, or None if already at root."""
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path or "/" not in path:
        return None
    parent_path = path.rsplit("/", 1)[0]
    if not parent_path or parent_path == "/":
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parent_path}"


def _parse_duckduckgo_html(html_content: str, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

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
            if "uddg=" in url:
                from urllib.parse import parse_qs
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                url = qs.get("uddg", [url])[0]

            results.append({"title": title, "url": url, "snippet": snippet})

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
    clean = re.sub(r"<[^>]+>", "", text)
    return html.unescape(clean)


def _html_to_text(html_content: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(br|p|div|h[1-6]|li|tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
