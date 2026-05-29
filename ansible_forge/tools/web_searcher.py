"""Web search and documentation reading tool for infrastructure automation."""

from __future__ import annotations

import contextlib
import html
import os
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
    "docs.nvidia.com",
})

_DEEP_CONTENT_LIMIT = 12000
_DEFAULT_CONTENT_LIMIT = 5000
_MIN_USEFUL_CONTENT = 150

_JINA_READER_URL = "https://r.jina.ai/"
_JINA_SEARCH_URL = "https://s.jina.ai/"
_JINA_TIMEOUT = 45
_JINA_CONTENT_LIMIT = 15000

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"
_TAVILY_TIMEOUT = 30
_TAVILY_MIN_SCORE = 0.3

_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

_SCOPE_DOMAINS: dict[str, list[str]] = {
    "ansible_docs": ["docs.ansible.com"],
    "stackoverflow": ["stackoverflow.com"],
    "galaxy": ["galaxy.ansible.com"],
}


def _is_docs_domain(url: str) -> bool:
    try:
        host = urlparse(url).hostname or ""
        return any(host == d or host.endswith(f".{d}") for d in _DOCS_DOMAINS)
    except Exception:
        return False


def _is_boilerplate(text: str) -> bool:
    if len(text) < _MIN_USEFUL_CONTENT:
        return True
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    short_lines = sum(1 for ln in lines if len(ln) < 40)
    if len(lines) > 5 and short_lines / len(lines) > 0.8:
        return True
    nav_markers = sum(
        1 for ln in lines
        if any(k in ln.lower() for k in ("skip to", "sign in", "log in", "cookie", "accept all", "menu"))
    )
    return len(lines) > 3 and nav_markers / len(lines) > 0.3


_cached_tavily_key: str | None = None
_cached_jina_key: str | None = None


def _resolve_env_key(var_name: str) -> str:
    key = os.environ.get(var_name, "").strip()
    if not key:
        from pathlib import Path
        env_file = Path.home() / ".ansibleforge" / ".env"
        if env_file.is_file():
            for line in env_file.read_text().splitlines():
                line = line.strip()
                if line.startswith(f"{var_name}=") and not line.startswith("#"):
                    key = line.split("=", 1)[1].strip()
                    break
    return key


def _resolve_tavily_key() -> str:
    global _cached_tavily_key
    if _cached_tavily_key is not None:
        return _cached_tavily_key
    _cached_tavily_key = _resolve_env_key("TAVILY_API_KEY")
    return _cached_tavily_key


def _resolve_jina_key() -> str:
    global _cached_jina_key
    if _cached_jina_key is not None:
        return _cached_jina_key
    _cached_jina_key = _resolve_env_key("JINA_API_KEY")
    return _cached_jina_key


def _jina_base_headers() -> dict[str, str]:
    headers: dict[str, str] = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    api_key = _resolve_jina_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _jina_reader_headers(is_docs: bool = False) -> dict[str, str]:
    headers = _jina_base_headers()
    headers["X-Engine"] = "browser"
    headers["X-Retain-Images"] = "none"
    headers["X-No-Cache"] = "true"
    headers["X-Remove-Selector"] = "nav,header,footer,.cookie-banner,.breadcrumb,#footer,#header"
    if is_docs:
        headers["X-Timeout"] = "40"
    return headers


def _jina_search_headers() -> dict[str, str]:
    headers = _jina_base_headers()
    headers["X-Retain-Images"] = "none"
    return headers


class WebSearcher(BaseTool):
    def __init__(self) -> None:
        self._url_cache: dict[str, str] = {}

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web or read a specific URL. Two modes:\n"
            "1. SEARCH mode (default): provide `query` to search the web. "
            "Returns result titles, URLs, relevance scores, and full content "
            "from top results. Uses AI-powered search with relevance ranking.\n"
            "2. READ mode: provide `url` to fetch and read a specific page. "
            "Use this to read official documentation, prerequisites pages, "
            "or any URL found in previous search results. Handles JS-rendered "
            "pages (e.g. Red Hat docs) automatically via fallback rendering.\n"
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
                        "Handles JavaScript-rendered pages automatically."
                    ),
                },
                "scope": {
                    "type": "string",
                    "enum": ["ansible_docs", "general", "galaxy", "stackoverflow"],
                    "description": (
                        "Search scope: 'ansible_docs' limits to docs.ansible.com, "
                        "'stackoverflow' limits to stackoverflow.com, "
                        "'galaxy' limits to galaxy.ansible.com, "
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

        max_results = min(max_results, 10)
        results, source, answer = await self._search_with_fallback(query, scope, max_results)

        if not results:
            return ToolResult.ok(
                output=f"No results found for: {query}",
                results=[],
            )

        fetched_contents: list[tuple[str, str]] = []
        if source == "tavily":
            for r in results[:5]:
                content = r.get("content", "")
                if content and not _is_boilerplate(content):
                    limit = _DEEP_CONTENT_LIMIT if _is_docs_domain(r["url"]) else _DEFAULT_CONTENT_LIMIT
                    fetched_contents.append((r["url"], content[:limit]))
                    self._url_cache[r["url"]] = content[:_JINA_CONTENT_LIMIT]
        elif source == "jina":
            for r in results[:3]:
                content = r.get("content", "")
                if content and not _is_boilerplate(content):
                    limit = _DEEP_CONTENT_LIMIT if _is_docs_domain(r["url"]) else _DEFAULT_CONTENT_LIMIT
                    fetched_contents.append((r["url"], content[:limit]))
                    self._url_cache[r["url"]] = content[:_JINA_CONTENT_LIMIT]
        else:
            for r in results[:2]:
                content = await self._fetch_url_with_fallback(r["url"])
                if content and not _is_boilerplate(content):
                    fetched_contents.append((r["url"], content[:_DEFAULT_CONTENT_LIMIT]))

        formatted = self._format_results(results, fetched_contents, answer)
        return ToolResult.ok(
            output=formatted,
            results=results,
            query=query,
        )

    async def _search_with_fallback(
        self, query: str, scope: str, max_results: int,
    ) -> tuple[list[dict[str, str]], str, str]:
        """Tavily first, then Jina Search, then DuckDuckGo."""
        tavily_key = _resolve_tavily_key()
        if tavily_key:
            try:
                results, answer = await self._search_tavily(
                    query, scope, max_results, tavily_key,
                )
                if results:
                    logger.info("search_via_tavily", query=query, count=len(results))
                    return results, "tavily", answer
            except Exception as exc:
                logger.info("tavily_search_fallback", error=str(exc)[:200])

        if _resolve_jina_key():
            try:
                results = await self._search_jina(query, scope, max_results)
                if results:
                    logger.info("search_via_jina", query=query, count=len(results))
                    return results, "jina", ""
            except Exception as exc:
                logger.info("jina_search_fallback", error=str(exc)[:200])

        ddg_query = self._apply_scope(query, scope)
        try:
            results = await self._search_duckduckgo(ddg_query, max_results)
            logger.info("search_via_duckduckgo", query=ddg_query, count=len(results))
            return results, "duckduckgo", ""
        except Exception as exc:
            logger.warning("all_search_failed", error=str(exc))
            return [], "none", ""

    @staticmethod
    async def _search_tavily(
        query: str, scope: str, max_results: int, api_key: str,
    ) -> tuple[list[dict[str, str]], str]:
        body: dict[str, Any] = {
            "query": query,
            "search_depth": "advanced",
            "max_results": max_results,
            "include_answer": True,
            "include_raw_content": "markdown",
        }

        domains = _SCOPE_DOMAINS.get(scope)
        if domains:
            body["include_domains"] = domains

        async with httpx.AsyncClient(
            timeout=_TAVILY_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                _TAVILY_SEARCH_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json=body,
            )
            resp.raise_for_status()

        data = resp.json()
        answer = data.get("answer", "") or ""

        results: list[dict[str, str]] = []
        for item in data.get("results", []):
            if not isinstance(item, dict):
                continue
            url = item.get("url", "").strip()
            title = item.get("title", "").strip()
            score = item.get("score", 0.0)
            if not url or not title or score < _TAVILY_MIN_SCORE:
                continue

            raw_content = item.get("raw_content", "") or ""
            snippet = item.get("content", "") or ""

            content = raw_content if raw_content else snippet
            if content:
                content = _clean_tavily_content(content)

            results.append({
                "title": title,
                "url": url,
                "snippet": snippet[:500],
                "content": content,
                "score": f"{score:.2f}",
            })

        return results, answer

    async def _fetch_url_direct(self, url: str) -> ToolResult:
        cached = self._url_cache.get(url)
        if cached:
            logger.info("url_cache_hit", url=url)
            return ToolResult.ok(
                output=f"**Page content from {url}:**\n\n{cached}",
                url=url,
            )

        try:
            content = await self._fetch_url_with_fallback(url, deep=True)
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
                "The page may require authentication or is entirely image-based. "
                "Try searching for an alternative source."
            )

        self._url_cache[url] = content
        return ToolResult.ok(
            output=f"**Page content from {url}:**\n\n{content}",
            url=url,
        )

    async def _fetch_url_with_fallback(
        self, url: str, deep: bool = False,
    ) -> str:
        content = ""
        with contextlib.suppress(Exception):
            content = await self._fetch_page_content(url, deep=deep)

        if content and not _is_boilerplate(content):
            return content

        logger.info("httpx_content_weak_trying_jina", url=url, httpx_len=len(content or ""))
        try:
            jina_content = await self._fetch_via_jina_reader(url)
            if jina_content and len(jina_content) > len(content or ""):
                return jina_content
        except Exception as exc:
            logger.info("jina_reader_fallback_failed", url=url, error=str(exc)[:200])

        return content

    @staticmethod
    async def _fetch_via_jina_reader(url: str) -> str:
        is_docs = _is_docs_domain(url)
        headers = _jina_reader_headers(is_docs=is_docs)

        async with httpx.AsyncClient(
            timeout=_JINA_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                _JINA_READER_URL,
                headers=headers,
                json={"url": url},
            )
            resp.raise_for_status()

        data = resp.json()
        payload = data.get("data", {})
        if not isinstance(payload, dict):
            return ""

        text = payload.get("content", "")
        if not text:
            return ""

        text = _clean_jina_markdown(text)
        limit = _JINA_CONTENT_LIMIT if is_docs else _DEEP_CONTENT_LIMIT
        return text[:limit]

    @staticmethod
    async def _search_jina(query: str, scope: str, max_results: int) -> list[dict[str, str]]:
        headers = _jina_search_headers()

        site_map = {
            "ansible_docs": "https://docs.ansible.com",
            "stackoverflow": "https://stackoverflow.com",
            "galaxy": "https://galaxy.ansible.com",
        }
        site = site_map.get(scope)
        if site:
            headers["X-Site"] = site

        async with httpx.AsyncClient(
            timeout=_JINA_TIMEOUT,
            follow_redirects=True,
        ) as client:
            resp = await client.post(
                _JINA_SEARCH_URL,
                headers=headers,
                json={"q": query},
            )
            resp.raise_for_status()

        data = resp.json()

        results: list[dict[str, str]] = []
        items = data.get("data", [])
        if not isinstance(items, list):
            return results

        for item in items[:max_results]:
            if not isinstance(item, dict):
                continue
            url = item.get("url", "").strip()
            title = item.get("title", "").strip()
            if not url or not title:
                continue
            content = item.get("content", "")
            if content:
                content = _clean_jina_markdown(content)
            results.append({
                "title": title,
                "url": url,
                "snippet": item.get("description", "")[:300],
                "content": content,
            })

        return results

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
            headers={"User-Agent": _BROWSER_UA},
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
                "User-Agent": _BROWSER_UA,
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
        answer: str = "",
    ) -> str:
        lines: list[str] = []

        if answer:
            lines.append("**AI Summary:**")
            lines.append(answer[:2000])
            lines.append("")

        lines.append(f"Found {len(results)} result(s):\n")
        for i, r in enumerate(results, 1):
            score = r.get("score", "")
            score_tag = f" [relevance: {score}]" if score else ""
            lines.append(f"{i}. **{r['title']}**{score_tag}")
            lines.append(f"   URL: {r['url']}")
            if r.get("snippet"):
                lines.append(f"   {r['snippet'][:300]}")
            lines.append("")

        for fetch_url, content in fetched_contents:
            lines.append("---")
            lines.append(f"**Content from {fetch_url}:**")
            lines.append(content[:6000])
            lines.append("")

        return "\n".join(lines)


def _parent_url(url: str) -> str | None:
    parsed = urlparse(url)
    path = parsed.path.rstrip("/")
    if not path or "/" not in path:
        return None
    parent_path = path.rsplit("/", 1)[0]
    if not parent_path or parent_path == "/":
        return None
    return f"{parsed.scheme}://{parsed.netloc}{parent_path}"


def _clean_jina_markdown(text: str) -> str:
    text = re.sub(r"^Title:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^URL Source:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^Published Time:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^Markdown Content:\s*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^Warning:.*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _clean_tavily_content(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


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
    main_content = _extract_main_content(html_content)
    if main_content:
        html_content = main_content

    text = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", "", html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<(br|p|div|h[1-6]|li|tr|dt|dd|section|article)[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _extract_main_content(html_content: str) -> str:
    for pattern in [
        re.compile(r"<main[^>]*>(.*?)</main>", re.DOTALL | re.IGNORECASE),
        re.compile(r'<article[^>]*>(.*?)</article>', re.DOTALL | re.IGNORECASE),
        re.compile(r'<div[^>]*role="main"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
        re.compile(r'<div[^>]*class="[^"]*(?:content|doc-body|main-content|article)[^"]*"[^>]*>(.*?)</div>', re.DOTALL | re.IGNORECASE),
    ]:
        match = pattern.search(html_content)
        if match and len(match.group(1)) > _MIN_USEFUL_CONTENT:
            return match.group(1)
    return ""
