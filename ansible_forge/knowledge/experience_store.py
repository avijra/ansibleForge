"""Outcome-driven experience store for compound self-learning.

Captures high-signal learning moments — successful patterns, error resolutions,
user corrections, and LLM-synthesized reflections — and makes them retrievable
via full-text search for future decisions.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ansible_forge.logging import get_logger

if TYPE_CHECKING:
    from ansible_forge.workspace.manager import Workspace

logger = get_logger(__name__)

_STOP_WORDS = frozenset({
    "a", "an", "the", "is", "it", "in", "on", "at", "to", "for", "of",
    "and", "or", "not", "but", "with", "from", "by", "as", "be", "was",
    "were", "been", "are", "am", "do", "does", "did", "has", "have",
    "had", "will", "would", "could", "should", "may", "might", "can",
    "this", "that", "these", "those", "i", "you", "we", "they", "my",
    "your", "our", "their", "me", "him", "her", "us", "them", "its",
    "what", "which", "who", "whom", "how", "where", "when", "why",
    "if", "then", "so", "just", "also", "about", "up", "out", "all",
    "no", "yes", "ok", "hey", "please", "need", "want", "like",
    "get", "got", "make", "let", "try", "use", "set", "run", "check",
    "look", "see", "now", "here", "there", "right", "don", "doesn",
    "didn", "won", "tell", "sure", "think", "know",
})


def _extract_search_keywords(text: str, max_keywords: int = 12) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_./-]{2,}", text)
    seen: set[str] = set()
    keywords: list[str] = []
    for w in words:
        lower = w.lower()
        if lower in _STOP_WORDS or lower in seen:
            continue
        if lower.startswith("http") or lower.startswith("//"):
            continue
        seen.add(lower)
        keywords.append(lower)
        if len(keywords) >= max_keywords:
            break
    return keywords


def _significant_words(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9_./-]{2,}", text.lower())
    return {w for w in words if w not in _STOP_WORDS}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS experiences (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    trigger TEXT NOT NULL,
    context_json TEXT NOT NULL DEFAULT '{}',
    solution TEXT NOT NULL,
    outcome TEXT,
    confidence REAL NOT NULL DEFAULT 0.5,
    created_at REAL NOT NULL,
    last_used REAL,
    use_count INTEGER NOT NULL DEFAULT 0,
    session_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_exp_type ON experiences(type);
CREATE INDEX IF NOT EXISTS idx_exp_confidence ON experiences(confidence DESC);
"""

_CREATE_FTS_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS experiences_fts USING fts5(
    trigger, solution, context_json,
    content='experiences', content_rowid='rowid'
);
"""

_SYNC_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS exp_ai AFTER INSERT ON experiences BEGIN
    INSERT INTO experiences_fts(rowid, trigger, solution, context_json)
    VALUES (new.rowid, new.trigger, new.solution, new.context_json);
END;
CREATE TRIGGER IF NOT EXISTS exp_ad AFTER DELETE ON experiences BEGIN
    INSERT INTO experiences_fts(experiences_fts, rowid, trigger, solution, context_json)
    VALUES ('delete', old.rowid, old.trigger, old.solution, old.context_json);
END;
CREATE TRIGGER IF NOT EXISTS exp_au AFTER UPDATE ON experiences BEGIN
    INSERT INTO experiences_fts(experiences_fts, rowid, trigger, solution, context_json)
    VALUES ('delete', old.rowid, old.trigger, old.solution, old.context_json);
    INSERT INTO experiences_fts(rowid, trigger, solution, context_json)
    VALUES (new.rowid, new.trigger, new.solution, new.context_json);
END;
"""


class Experience:
    __slots__ = (
        "id", "type", "trigger", "context", "solution",
        "outcome", "confidence", "created_at", "last_used",
        "use_count", "session_id",
    )

    def __init__(
        self,
        *,
        id: str = "",
        type: str = "",
        trigger: str = "",
        context: dict[str, Any] | None = None,
        solution: str = "",
        outcome: str = "",
        confidence: float = 0.5,
        created_at: float = 0.0,
        last_used: float | None = None,
        use_count: int = 0,
        session_id: str = "",
    ) -> None:
        self.id = id or uuid.uuid4().hex[:12]
        self.type = type
        self.trigger = trigger
        self.context = context or {}
        self.solution = solution
        self.outcome = outcome
        self.confidence = confidence
        self.created_at = created_at or time.time()
        self.last_used = last_used
        self.use_count = use_count
        self.session_id = session_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "trigger": self.trigger,
            "context": self.context,
            "solution": self.solution,
            "outcome": self.outcome,
            "confidence": self.confidence,
        }


class ExperienceStore:
    """SQLite + FTS5 backed experience store for self-learning."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".ansibleforge" / "knowledge" / "experiences.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_CREATE_SQL)
            try:
                conn.executescript(_CREATE_FTS_SQL)
                conn.executescript(_SYNC_FTS_TRIGGERS)
            except sqlite3.OperationalError:
                logger.debug("fts5_setup_skipped", exc_info=True)
            conn.close()
        logger.info("experience_store_initialized", path=str(self._db_path))

    def save(self, exp: Experience) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO experiences "
                "(id, type, trigger, context_json, solution, outcome, "
                " confidence, created_at, last_used, use_count, session_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                " solution=excluded.solution, outcome=excluded.outcome, "
                " confidence=excluded.confidence, last_used=excluded.last_used, "
                " use_count=excluded.use_count",
                (
                    exp.id, exp.type, exp.trigger,
                    json.dumps(exp.context), exp.solution, exp.outcome,
                    exp.confidence, exp.created_at, exp.last_used,
                    exp.use_count, exp.session_id,
                ),
            )
            conn.commit()
            conn.close()

    def record_use(self, experience_id: str) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE experiences SET use_count = use_count + 1, last_used = ? WHERE id = ?",
                (now, experience_id),
            )
            conn.commit()
            conn.close()

    def reward(self, experience_id: str, success: bool) -> None:
        delta = 0.05 if success else -0.08
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE experiences SET confidence = MAX(MIN(confidence + ?, 1.0), 0.05) WHERE id = ?",
                (delta, experience_id),
            )
            conn.commit()
            conn.close()

    def search(
        self, query: str, limit: int = 5, min_confidence: float = 0.3
    ) -> list[Experience]:
        if not query.strip():
            return []
        keywords = _extract_search_keywords(query)
        if not keywords:
            return []
        fts_query = " OR ".join(keywords)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT e.id, e.type, e.trigger, e.context_json, "
                    "  e.solution, e.outcome, e.confidence, e.created_at, "
                    "  e.last_used, e.use_count, e.session_id "
                    "FROM experiences_fts f "
                    "JOIN experiences e ON e.rowid = f.rowid "
                    "WHERE experiences_fts MATCH ? "
                    "  AND e.confidence >= ? "
                    "ORDER BY rank "
                    "LIMIT ?",
                    (fts_query, min_confidence, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            conn.close()
        return [self._row_to_experience(r) for r in rows]

    def search_by_type(
        self, query: str, exp_type: str, limit: int = 5, min_confidence: float = 0.3,
    ) -> list[Experience]:
        if not query.strip():
            return []
        keywords = _extract_search_keywords(query)
        if not keywords:
            return []
        fts_query = " OR ".join(keywords)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT e.id, e.type, e.trigger, e.context_json, "
                    "  e.solution, e.outcome, e.confidence, e.created_at, "
                    "  e.last_used, e.use_count, e.session_id "
                    "FROM experiences_fts f "
                    "JOIN experiences e ON e.rowid = f.rowid "
                    "WHERE experiences_fts MATCH ? "
                    "  AND e.type = ? AND e.confidence >= ? "
                    "ORDER BY rank "
                    "LIMIT ?",
                    (fts_query, exp_type, min_confidence, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            conn.close()
        return [self._row_to_experience(r) for r in rows]

    def query_by_type(
        self, exp_type: str, limit: int = 10
    ) -> list[Experience]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, type, trigger, context_json, solution, outcome, "
                "confidence, created_at, last_used, use_count, session_id "
                "FROM experiences WHERE type = ? "
                "ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (exp_type, limit),
            ).fetchall()
            conn.close()
        return [self._row_to_experience(r) for r in rows]

    def query_by_context(
        self,
        exp_type: str | None = None,
        module: str | None = None,
        limit: int = 5,
    ) -> list[Experience]:
        conditions = []
        params: list[Any] = []
        if exp_type:
            conditions.append("type = ?")
            params.append(exp_type)
        if module:
            conditions.append("context_json LIKE ?")
            params.append(f"%{module}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                f"SELECT id, type, trigger, context_json, solution, outcome, "
                f"confidence, created_at, last_used, use_count, session_id "
                f"FROM experiences WHERE {where} "
                f"ORDER BY confidence DESC, created_at DESC LIMIT ?",
                params,
            ).fetchall()
            conn.close()
        return [self._row_to_experience(r) for r in rows]

    def get_rules(self, limit: int = 5) -> list[Experience]:
        return self.query_by_type("rule", limit)

    def find_similar(self, exp_type: str, trigger: str, solution: str, threshold: float = 0.4) -> Experience | None:
        existing = self.query_by_type(exp_type, limit=100)
        trigger_kw = _significant_words(trigger)
        solution_kw = _significant_words(solution)
        if not trigger_kw and not solution_kw:
            return None

        best: Experience | None = None
        best_score = 0.0
        for exp in existing:
            exp_trigger_kw = _significant_words(exp.trigger)
            exp_solution_kw = _significant_words(exp.solution)
            t_sim = _jaccard(trigger_kw, exp_trigger_kw)
            s_sim = _jaccard(solution_kw, exp_solution_kw)
            score = t_sim * 0.4 + s_sim * 0.6
            if score >= threshold and score > best_score:
                best = exp
                best_score = score
        return best

    def deduplicate(self, threshold: float = 0.4) -> int:
        all_exps = self.query_by_type("reflection", limit=500)
        all_exps.extend(self.query_by_type("error_resolution", limit=500))

        keep: list[Experience] = []
        remove_ids: list[str] = []

        for exp in all_exps:
            exp_kw_trigger = _significant_words(exp.trigger)
            exp_kw_solution = _significant_words(exp.solution)

            is_dup = False
            for kept in keep:
                t_sim = _jaccard(exp_kw_trigger, _significant_words(kept.trigger))
                s_sim = _jaccard(exp_kw_solution, _significant_words(kept.solution))
                score = t_sim * 0.4 + s_sim * 0.6
                if score >= threshold:
                    if exp.confidence > kept.confidence or exp.use_count > kept.use_count:
                        remove_ids.append(kept.id)
                        keep.remove(kept)
                        keep.append(exp)
                    else:
                        remove_ids.append(exp.id)
                    is_dup = True
                    break
            if not is_dup:
                keep.append(exp)

        if remove_ids:
            with self._lock:
                conn = self._connect()
                for rid in remove_ids:
                    conn.execute("DELETE FROM experiences WHERE id = ?", (rid,))
                conn.commit()
                conn.close()
            logger.info("experiences_deduplicated", removed=len(remove_ids), kept=len(keep))
        return len(remove_ids)

    def prune_subsumed(self, threshold: float = 0.35) -> int:
        rules = self.query_by_type("rule", limit=50)
        if not rules:
            return 0
        rule_keywords = [
            (_significant_words(r.trigger), _significant_words(r.solution))
            for r in rules
        ]

        candidates = self.query_by_type("reflection", limit=500)
        candidates.extend(self.query_by_type("error_resolution", limit=500))

        remove_ids: list[str] = []
        for exp in candidates:
            if exp.use_count > 2 or exp.confidence > 0.7:
                continue
            exp_t = _significant_words(exp.trigger)
            exp_s = _significant_words(exp.solution)
            for rule_t, rule_s in rule_keywords:
                t_sim = _jaccard(exp_t, rule_t)
                s_sim = _jaccard(exp_s, rule_s)
                score = t_sim * 0.4 + s_sim * 0.6
                if score >= threshold:
                    remove_ids.append(exp.id)
                    break

        if remove_ids:
            with self._lock:
                conn = self._connect()
                for rid in remove_ids:
                    conn.execute("DELETE FROM experiences WHERE id = ?", (rid,))
                conn.commit()
                conn.close()
            logger.info("experiences_pruned_subsumed", removed=len(remove_ids))
        return len(remove_ids)

    def prune_stale(self, max_age_days: int = 30, min_confidence: float = 0.3) -> int:
        cutoff = time.time() - (max_age_days * 86400)
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "DELETE FROM experiences WHERE use_count = 0 AND confidence < ? "
                "AND created_at < ? AND type != 'rule'",
                (min_confidence, cutoff),
            )
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
        if deleted:
            logger.info("experiences_pruned", count=deleted)
        return deleted

    def count(self, exp_type: str | None = None) -> int:
        with self._lock:
            conn = self._connect()
            if exp_type:
                row = conn.execute(
                    "SELECT COUNT(*) FROM experiences WHERE type = ?",
                    (exp_type,),
                ).fetchone()
            else:
                row = conn.execute("SELECT COUNT(*) FROM experiences").fetchone()
            conn.close()
        return row[0] if row else 0

    def get_all_by_type_grouped(self, min_group_size: int = 3) -> dict[str, list[Experience]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT id, type, trigger, context_json, solution, outcome, "
                "confidence, created_at, last_used, use_count, session_id "
                "FROM experiences WHERE type != 'rule' "
                "ORDER BY type, created_at DESC",
            ).fetchall()
            conn.close()

        groups: dict[str, list[Experience]] = {}
        for r in rows:
            exp = self._row_to_experience(r)
            groups.setdefault(exp.type, []).append(exp)
        return {k: v for k, v in groups.items() if len(v) >= min_group_size}

    @staticmethod
    def _row_to_experience(row: tuple[Any, ...]) -> Experience:
        ctx = row[3]
        if isinstance(ctx, str):
            try:
                ctx = json.loads(ctx)
            except json.JSONDecodeError:
                ctx = {}
        return Experience(
            id=row[0],
            type=row[1],
            trigger=row[2],
            context=ctx,
            solution=row[4],
            outcome=row[5] or "",
            confidence=row[6],
            created_at=row[7],
            last_used=row[8],
            use_count=row[9],
            session_id=row[10] or "",
        )


_MODULE_PATTERN = re.compile(r"\b[a-z_]+\.[a-z_]+\.[a-z_]+\b")


def extract_modules_from_workspace(workspace: Workspace | None) -> set[str]:
    modules: set[str] = set()
    if workspace is None:
        return modules
    project_dir = workspace.project_dir
    if not project_dir.is_dir():
        return modules
    for yml_file in project_dir.rglob("*.yml"):
        try:
            content = yml_file.read_text(encoding="utf-8")
            modules.update(_MODULE_PATTERN.findall(content))
        except OSError:
            pass
    return modules


def _format_experience(exp: Experience) -> str:
    confidence_pct = int(exp.confidence * 100)
    return f"  [{exp.type}] (confidence: {confidence_pct}%) {exp.solution}"


def build_experience_context(
    store: ExperienceStore,
    user_message: str,
    modules: set[str] | None = None,
    *,
    record_usage: bool = True,
) -> tuple[str, list[str]]:
    """Build experience context for the agent prompt.

    Returns (context_text, list_of_experience_ids_used).
    Set record_usage=False when calling from plan generation to avoid
    double-counting usage.
    """
    sections: list[str] = []
    used_ids: list[str] = []

    relevant = store.search(user_message, limit=5, min_confidence=0.35)
    if relevant:
        lines = [_format_experience(e) for e in relevant]
        sections.append("Relevant past experiences:\n" + "\n".join(lines))
        for exp in relevant:
            if record_usage:
                store.record_use(exp.id)
            used_ids.append(exp.id)

    if modules:
        for mod in sorted(modules):
            errors = store.query_by_context(exp_type="error_resolution", module=mod, limit=3)
            high_conf = [e for e in errors if e.confidence >= 0.5]
            if high_conf:
                lines = [f"  - {e.trigger[:150]} -> {e.solution[:150]}" for e in high_conf]
                sections.append(f"Known issues with `{mod}`:\n" + "\n".join(lines))
                for e in high_conf:
                    if record_usage:
                        store.record_use(e.id)
                    used_ids.append(e.id)

    recipes = store.search_by_type(user_message, exp_type="recipe", limit=3)
    if recipes:
        lines = []
        for r in recipes:
            ctx = r.context or {}
            host_list = ", ".join(ctx.get("hosts", [])[:3])
            mod_list = ", ".join(ctx.get("modules", [])[:5])
            detail = r.solution[:200]
            if host_list:
                detail += f" (hosts: {host_list})"
            if mod_list:
                detail += f" (modules: {mod_list})"
            lines.append(f"  - {detail}")
        sections.append("Successful patterns from previous runs:\n" + "\n".join(lines))
        for r in recipes:
            if record_usage:
                store.record_use(r.id)
            used_ids.append(r.id)

    rules = store.get_rules(limit=5)
    if rules:
        lines = [f"  - {r.solution}" for r in rules]
        sections.append("Learned rules:\n" + "\n".join(lines))
        for r in rules:
            if record_usage:
                store.record_use(r.id)
            used_ids.append(r.id)

    if sections:
        logger.info(
            "experience_context_built",
            section_count=len(sections),
            experience_ids_used=len(used_ids),
        )
    else:
        keywords = _extract_search_keywords(user_message, max_keywords=6)
        logger.info(
            "experience_context_empty",
            search_keywords=keywords,
            total_experiences=store.count(),
        )

    if not sections:
        return "", []

    unique_ids = list(dict.fromkeys(used_ids))
    return "---\nExperience context:\n" + "\n\n".join(sections) + "\n", unique_ids
