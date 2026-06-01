"""Cross-project learning store for bug patterns and successful strategies.

Persists error-fix pairs and successful patterns to ``~/.tuyere/learning/``
so future sessions across any project can benefit from past experience.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_LEARNING_DIR = Path.home() / ".tuyere" / "learning"
_MAX_ENTRIES = 100
_MAX_ENTRY_CHARS = 1500


class LearningStore:
    _instance: LearningStore | None = None

    def __init__(self, base_dir: Path | None = None) -> None:
        self._dir = base_dir or _LEARNING_DIR
        self._bugs_dir = self._dir / "bugs"
        self._patterns_dir = self._dir / "patterns"

    @classmethod
    def get_instance(cls) -> LearningStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record_bug_fix(
        self,
        error_pattern: str,
        fix_description: str,
        tool_name: str = "",
        context: str = "",
    ) -> str:
        self._bugs_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "type": "bug_fix",
            "error_pattern": error_pattern[:500],
            "fix": fix_description[:800],
            "tool": tool_name,
            "context": context[:200],
            "timestamp": time.time(),
        }
        filename = f"bug-{int(time.time())}-{tool_name or 'unknown'}.json"
        path = self._bugs_dir / filename
        path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        self._enforce_limit(self._bugs_dir)
        logger.info("learning_bug_recorded", file=filename)
        return f"Bug pattern recorded: {filename}"

    def record_pattern(
        self,
        pattern_name: str,
        description: str,
        context: str = "",
    ) -> str:
        self._patterns_dir.mkdir(parents=True, exist_ok=True)
        entry = {
            "type": "pattern",
            "name": pattern_name[:200],
            "description": description[:800],
            "context": context[:200],
            "timestamp": time.time(),
        }
        slug = pattern_name.lower().replace(" ", "-")[:50]
        filename = f"pattern-{slug}.json"
        path = self._patterns_dir / filename
        path.write_text(json.dumps(entry, indent=2), encoding="utf-8")
        self._enforce_limit(self._patterns_dir)
        logger.info("learning_pattern_recorded", file=filename)
        return f"Pattern recorded: {filename}"

    def recall_bugs(self, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
        return self._search(self._bugs_dir, keywords, limit)

    def recall_patterns(self, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
        return self._search(self._patterns_dir, keywords, limit)

    def recall_all(self, keywords: list[str], limit: int = 5) -> list[dict[str, Any]]:
        bugs = self.recall_bugs(keywords, limit)
        patterns = self.recall_patterns(keywords, limit)
        combined = bugs + patterns
        combined.sort(key=lambda x: x.get("score", 0), reverse=True)
        return combined[:limit]

    def format_context(self, keywords: list[str]) -> str:
        entries = self.recall_all(keywords, limit=3)
        if not entries:
            return ""
        lines = ["---", "CROSS-PROJECT LEARNING (past fixes and patterns):"]
        for e in entries:
            if e.get("type") == "bug_fix":
                lines.append(
                    f"- BUG FIX ({e.get('tool', '?')}): "
                    f"error='{e.get('error_pattern', '')[:100]}' "
                    f"→ fix: {e.get('fix', '')[:200]}"
                )
            else:
                lines.append(
                    f"- PATTERN: {e.get('name', '?')}: "
                    f"{e.get('description', '')[:200]}"
                )
        lines.append("---")
        return "\n".join(lines)

    def _search(
        self, directory: Path, keywords: list[str], limit: int,
    ) -> list[dict[str, Any]]:
        if not directory.is_dir():
            return []
        lower_kw = [k.lower() for k in keywords if k]
        if not lower_kw:
            return []

        scored: list[tuple[float, dict[str, Any]]] = []
        for path in directory.glob("*.json"):
            try:
                entry = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            searchable = json.dumps(entry).lower()
            score = sum(1.0 for kw in lower_kw if kw in searchable)
            if score > 0:
                entry["score"] = score
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:limit]]

    @staticmethod
    def _enforce_limit(directory: Path) -> None:
        files = sorted(directory.glob("*.json"), key=lambda f: f.stat().st_mtime)
        while len(files) > _MAX_ENTRIES:
            oldest = files.pop(0)
            oldest.unlink(missing_ok=True)
