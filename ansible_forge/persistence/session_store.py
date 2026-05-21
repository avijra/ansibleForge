"""SQLite-backed session persistence for conversation replay.

All SQLite operations run inside a dedicated thread via run_in_executor
so they never block the asyncio event loop.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    project_path TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    data TEXT NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id, id);
"""

_MIGRATE_PROJECT_PATH = (
    "ALTER TABLE sessions ADD COLUMN project_path TEXT"
)

_MIGRATE_SEQ = (
    "ALTER TABLE events ADD COLUMN seq INTEGER DEFAULT 0"
)

_db_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="session-db")


class SessionStore:
    """Persists session metadata and events to a SQLite database."""

    _instance: SessionStore | None = None
    _cls_lock = threading.Lock()

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".ansibleforge" / "sessions.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls, db_path: Path | None = None) -> SessionStore:
        if cls._instance is None:
            with cls._cls_lock:
                if cls._instance is None:
                    cls._instance = cls(db_path)
        return cls._instance

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_CREATE_SQL)
            self._migrate(conn)
            self._init_fts(conn)
            conn.close()
        logger.info("session_store_initialized", path=str(self._db_path))

    @staticmethod
    def _init_fts(conn: sqlite3.Connection) -> None:
        try:
            conn.executescript("""
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
    data,
    content='events', content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS events_fts_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, data) VALUES (new.id, new.data);
END;
CREATE TRIGGER IF NOT EXISTS events_fts_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, data)
    VALUES ('delete', old.id, old.data);
END;
""")
            indexed = conn.execute("SELECT COUNT(*) FROM events_fts").fetchone()[0]
            total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            if total > 0 and indexed == 0:
                conn.execute(
                    "INSERT INTO events_fts(rowid, data) "
                    "SELECT id, data FROM events"
                )
                conn.commit()
                logger.info("session_fts5_backfilled", rows=total)
        except sqlite3.OperationalError:
            logger.debug("session_fts5_setup_skipped", exc_info=True)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "project_path" not in cols:
            conn.execute(_MIGRATE_PROJECT_PATH)
            conn.commit()

        event_cols = {row[1] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
        if "seq" not in event_cols:
            conn.execute(_MIGRATE_SEQ)
            conn.commit()

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_events_session_seq ON events(session_id, seq)"
        )
        conn.commit()

    def _run_in_lock(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Execute *fn* under the threading lock — called from the DB executor thread."""
        with self._lock:
            return fn(*args, **kwargs)

    async def _offload(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        """Run a blocking DB function off the event loop via the shared executor."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            _db_executor, partial(self._run_in_lock, fn, *args, **kwargs)
        )

    # ------------------------------------------------------------------
    # Sync internals (run on the DB executor thread)
    # ------------------------------------------------------------------

    def _save_session_sync(
        self,
        session_id: str,
        title: str | None,
        status: str,
        project_path: str | None,
    ) -> None:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO sessions (session_id, title, status, project_path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "title=COALESCE(?, title), status=?, project_path=COALESCE(?, project_path), updated_at=?",
                (session_id, title, status, project_path, now, now, title, status, project_path, now),
            )
            conn.commit()
        finally:
            conn.close()

    def _save_event_sync(
        self,
        session_id: str,
        event_type: str,
        data: dict[str, Any],
        seq: int,
    ) -> None:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute(
                "INSERT INTO events (session_id, event_type, data, timestamp, seq) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, event_type, json.dumps(data), now, seq),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
        finally:
            conn.close()

    def _list_sessions_sync(self, limit: int) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "session_id": r[0], "title": r[1], "status": r[2],
                "created_at": r[3], "updated_at": r[4], "project_path": r[5],
            }
            for r in rows
        ]

    def _get_events_sync(self, session_id: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT event_type, data, timestamp FROM events "
                "WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"event_type": r[0], "data": json.loads(r[1]), "timestamp": r[2]}
            for r in rows
        ]

    def _get_session_sync(self, session_id: str) -> dict[str, Any] | None:
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
        finally:
            conn.close()
        if row is None:
            return None
        return {
            "session_id": row[0], "title": row[1], "status": row[2],
            "created_at": row[3], "updated_at": row[4], "project_path": row[5],
        }

    def _delete_session_sync(self, session_id: str) -> bool:
        conn = self._connect()
        try:
            conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    def _reset_session_sync(self, session_id: str) -> bool:
        now = time.time()
        conn = self._connect()
        try:
            conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            cur = conn.execute(
                "UPDATE sessions SET status='active', updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
        finally:
            conn.close()
        return cur.rowcount > 0

    def _get_events_since_seq_sync(
        self, session_id: str, from_seq: int
    ) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT event_type, data, timestamp, seq FROM events "
                "WHERE session_id=? AND seq > ? ORDER BY id",
                (session_id, from_seq),
            ).fetchall()
        finally:
            conn.close()
        return [
            {"event_type": r[0], "data": json.loads(r[1]), "timestamp": r[2], "seq": r[3]}
            for r in rows
        ]

    def _list_by_project_path_sync(self, project_path: str) -> list[dict[str, Any]]:
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions WHERE project_path=? ORDER BY updated_at DESC",
                (project_path,),
            ).fetchall()
        finally:
            conn.close()
        return [
            {
                "session_id": r[0], "title": r[1], "status": r[2],
                "created_at": r[3], "updated_at": r[4], "project_path": r[5],
            }
            for r in rows
        ]

    def _search_events_sync(self, query: str, limit: int) -> list[dict[str, Any]]:
        import re as _re
        keywords = _re.findall(r"\w{3,}", query.lower())
        if not keywords:
            return []
        fts_query = " OR ".join(keywords)
        conn = self._connect()
        try:
            try:
                rows = conn.execute(
                    "SELECT e.session_id, e.event_type, e.data, e.timestamp, "
                    "  s.title, s.created_at "
                    "FROM events_fts f "
                    "JOIN events e ON e.id = f.rowid "
                    "JOIN sessions s ON s.session_id = e.session_id "
                    "WHERE events_fts MATCH ? "
                    "ORDER BY rank "
                    "LIMIT ?",
                    (fts_query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT e.session_id, e.event_type, e.data, e.timestamp, "
                    "  s.title, s.created_at "
                    "FROM events e "
                    "JOIN sessions s ON s.session_id = e.session_id "
                    "WHERE e.data LIKE ? "
                    "ORDER BY e.timestamp DESC "
                    "LIMIT ?",
                    (f"%{keywords[0]}%", limit),
                ).fetchall()
        finally:
            conn.close()
        results: list[dict[str, Any]] = []
        for r in rows:
            try:
                data = json.loads(r[2])
            except (json.JSONDecodeError, TypeError):
                data = {"raw": r[2][:200]}
            content = data.get("content", data.get("output", ""))
            if isinstance(content, str) and len(content) > 300:
                content = content[:300] + "..."
            results.append({
                "session_id": r[0], "event_type": r[1], "excerpt": content,
                "timestamp": r[3],
                "session_title": r[4] or "Untitled session",
                "session_date": time.strftime("%Y-%m-%d", time.localtime(r[5])) if r[5] else "",
            })
        return results

    # ------------------------------------------------------------------
    # Public sync API (kept for callers outside an event loop, e.g. init)
    # ------------------------------------------------------------------

    def save_session(self, session_id: str, title: str | None = None,
                     status: str = "active", project_path: str | None = None) -> None:
        self._run_in_lock(self._save_session_sync, session_id, title, status, project_path)

    def save_event(self, session_id: str, event_type: str,
                   data: dict[str, Any], seq: int = 0) -> None:
        self._run_in_lock(self._save_event_sync, session_id, event_type, data, seq)

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._run_in_lock(self._list_sessions_sync, limit)

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        return self._run_in_lock(self._get_events_sync, session_id)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        return self._run_in_lock(self._get_session_sync, session_id)

    def delete_session(self, session_id: str) -> bool:
        return self._run_in_lock(self._delete_session_sync, session_id)

    def reset_session(self, session_id: str) -> bool:
        return self._run_in_lock(self._reset_session_sync, session_id)

    def get_events_since_seq(self, session_id: str, from_seq: int) -> list[dict[str, Any]]:
        return self._run_in_lock(self._get_events_since_seq_sync, session_id, from_seq)

    def list_by_project_path(self, project_path: str) -> list[dict[str, Any]]:
        return self._run_in_lock(self._list_by_project_path_sync, project_path)

    def search_events(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return self._run_in_lock(self._search_events_sync, query, limit)

    # ------------------------------------------------------------------
    # Async API — use from FastAPI route handlers
    # ------------------------------------------------------------------

    async def asave_session(self, session_id: str, title: str | None = None,
                            status: str = "active", project_path: str | None = None) -> None:
        await self._offload(self._save_session_sync, session_id, title, status, project_path)

    async def asave_event(self, session_id: str, event_type: str,
                          data: dict[str, Any], seq: int = 0) -> None:
        await self._offload(self._save_event_sync, session_id, event_type, data, seq)

    async def alist_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        return await self._offload(self._list_sessions_sync, limit)

    async def aget_events(self, session_id: str) -> list[dict[str, Any]]:
        return await self._offload(self._get_events_sync, session_id)

    async def aget_session(self, session_id: str) -> dict[str, Any] | None:
        return await self._offload(self._get_session_sync, session_id)

    async def adelete_session(self, session_id: str) -> bool:
        return await self._offload(self._delete_session_sync, session_id)

    async def areset_session(self, session_id: str) -> bool:
        return await self._offload(self._reset_session_sync, session_id)

    async def aget_events_since_seq(self, session_id: str, from_seq: int) -> list[dict[str, Any]]:
        return await self._offload(self._get_events_since_seq_sync, session_id, from_seq)

    async def alist_by_project_path(self, project_path: str) -> list[dict[str, Any]]:
        return await self._offload(self._list_by_project_path_sync, project_path)

    async def asearch_events(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return await self._offload(self._search_events_sync, query, limit)
