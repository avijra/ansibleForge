"""Workspace file context injection for @ mentions.

Parses @file references from user messages, reads their content, and
injects it into the agent's context so it has precise file-level knowledge.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_AT_MENTION_RE = re.compile(r"@([\w./_-]+\.(?:ya?ml|tf|cfg|ini|j2|json|toml|md|sh|py|hcl|conf))", re.IGNORECASE)

_MAX_FILE_SIZE = 50_000
_MAX_INJECTED_FILES = 5
_MAX_CONTENT_PER_FILE = 8_000


def extract_mentions(message: str) -> list[str]:
    return _AT_MENTION_RE.findall(message)


def resolve_mentioned_files(workspace_path: Path, mentions: list[str]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    for mention in mentions[:_MAX_INJECTED_FILES]:
        if mention in seen:
            continue
        seen.add(mention)

        candidates = [
            workspace_path / mention,
            workspace_path / "inventory" / mention,
            workspace_path / "roles" / mention,
        ]

        if not any("/" in mention for _ in [1]):
            for match in workspace_path.rglob(mention):
                if ".tuyere" not in str(match) and match.is_file():
                    candidates.insert(0, match)
                    break

        for candidate in candidates:
            if candidate.is_file() and candidate.stat().st_size <= _MAX_FILE_SIZE:
                try:
                    content = candidate.read_text(errors="replace")
                    if len(content) > _MAX_CONTENT_PER_FILE:
                        content = content[:_MAX_CONTENT_PER_FILE] + "\n... (truncated)"
                    rel_path = str(candidate.relative_to(workspace_path))
                    results.append({
                        "path": rel_path,
                        "content": content,
                        "size": candidate.stat().st_size,
                    })
                    break
                except Exception:
                    logger.debug("mention_read_failed", file=str(candidate), exc_info=True)

    return results


def build_mention_context(workspace_path: Path, message: str) -> str:
    mentions = extract_mentions(message)
    if not mentions:
        return ""

    files = resolve_mentioned_files(workspace_path, mentions)
    if not files:
        return ""

    parts = ["\n## Referenced files (from @ mentions)"]
    for f in files:
        parts.append(f"\n### {f['path']}\n```\n{f['content']}\n```")

    logger.info("mention_context_built", file_count=len(files), mentions=mentions)
    return "\n".join(parts)


def search_workspace_files(
    workspace_path: Path,
    query: str = "",
    limit: int = 20,
) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    query_lower = query.lower()

    skip_dirs = {".tuyere", ".git", "__pycache__", "node_modules", ".terraform", "artifacts"}
    extensions = {".yml", ".yaml", ".tf", ".cfg", ".ini", ".j2", ".json", ".toml", ".md", ".sh", ".py", ".hcl", ".conf"}

    for path in workspace_path.rglob("*"):
        if any(part in skip_dirs for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix.lower() not in extensions:
            continue

        rel = str(path.relative_to(workspace_path))
        if query_lower and query_lower not in rel.lower():
            continue

        results.append({
            "path": rel,
            "name": path.name,
            "type": path.suffix.lstrip("."),
        })

        if len(results) >= limit:
            break

    results.sort(key=lambda r: r["path"])
    return results
