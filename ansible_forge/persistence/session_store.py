"""SQLite-backed session persistence for conversation replay."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
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


class SessionStore:
    """Persists session metadata and events to a SQLite database."""

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".ansibleforge" / "sessions.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript(_CREATE_SQL)
            self._migrate(conn)
            conn.close()
        logger.info("session_store_initialized", path=str(self._db_path))

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(sessions)").fetchall()}
        if "project_path" not in cols:
            conn.execute(_MIGRATE_PROJECT_PATH)
            conn.commit()

    def save_session(
        self,
        session_id: str,
        title: str | None = None,
        status: str = "active",
        project_path: str | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO sessions (session_id, title, status, project_path, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "title=COALESCE(?, title), status=?, project_path=COALESCE(?, project_path), updated_at=?",
                (session_id, title, status, project_path, now, now, title, status, project_path, now),
            )
            conn.commit()
            conn.close()

    def save_event(self, session_id: str, event_type: str, data: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO events (session_id, event_type, data, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, event_type, json.dumps(data), now),
            )
            conn.execute(
                "UPDATE sessions SET updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
            conn.close()

    def list_sessions(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            conn.close()
        return [
            {
                "session_id": r[0],
                "title": r[1],
                "status": r[2],
                "created_at": r[3],
                "updated_at": r[4],
                "project_path": r[5],
            }
            for r in rows
        ]

    def get_events(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT event_type, data, timestamp FROM events "
                "WHERE session_id=? ORDER BY id",
                (session_id,),
            ).fetchall()
            conn.close()
        return [
            {
                "event_type": r[0],
                "data": json.loads(r[1]),
                "timestamp": r[2],
            }
            for r in rows
        ]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions WHERE session_id=?",
                (session_id,),
            ).fetchone()
            conn.close()
        if row is None:
            return None
        return {
            "session_id": row[0],
            "title": row[1],
            "status": row[2],
            "created_at": row[3],
            "updated_at": row[4],
            "project_path": row[5],
        }

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            conn.commit()
            conn.close()
            return cur.rowcount > 0

    def reset_session(self, session_id: str) -> bool:
        """Delete all events for a session but keep the session row itself."""
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute("DELETE FROM events WHERE session_id=?", (session_id,))
            cur = conn.execute(
                "UPDATE sessions SET status='active', updated_at=? WHERE session_id=?",
                (now, session_id),
            )
            conn.commit()
            conn.close()
            return cur.rowcount > 0

    def list_by_project_path(self, project_path: str) -> list[dict[str, Any]]:
        """Return all sessions associated with a specific project directory."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT session_id, title, status, created_at, updated_at, project_path "
                "FROM sessions WHERE project_path=? ORDER BY updated_at DESC",
                (project_path,),
            ).fetchall()
            conn.close()
        return [
            {
                "session_id": r[0],
                "title": r[1],
                "status": r[2],
                "created_at": r[3],
                "updated_at": r[4],
                "project_path": r[5],
            }
            for r in rows
        ]
