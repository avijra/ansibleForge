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
                "UPDATE experiences SET use_count = use_count + 1, "
                "last_used = ?, confidence = MIN(confidence + 0.05, 1.0) "
                "WHERE id = ?",
                (now, experience_id),
            )
            conn.commit()
            conn.close()

    def search(self, query: str, limit: int = 5) -> list[Experience]:
        if not query.strip():
            return []
        safe_query = " ".join(
            w for w in query.split() if w and not w.startswith("-")
        )
        if not safe_query:
            return []
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
                    "ORDER BY rank "
                    "LIMIT ?",
                    (safe_query, limit),
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
) -> str:
    sections: list[str] = []

    relevant = store.search(user_message, limit=5)
    if relevant:
        lines = [_format_experience(e) for e in relevant]
        sections.append("Relevant past experiences:\n" + "\n".join(lines))
        for exp in relevant:
            store.record_use(exp.id)

    if modules:
        for mod in sorted(modules):
            errors = store.query_by_context(exp_type="error_resolution", module=mod, limit=3)
            if errors:
                lines = [f"  - {e.trigger[:150]} -> {e.solution[:150]}" for e in errors]
                sections.append(f"Known issues with `{mod}`:\n" + "\n".join(lines))

    rules = store.get_rules(limit=5)
    if rules:
        lines = [f"  - {r.solution}" for r in rules]
        sections.append("Learned rules:\n" + "\n".join(lines))

    if not sections:
        return ""

    return "---\nExperience context:\n" + "\n\n".join(sections) + "\n"
