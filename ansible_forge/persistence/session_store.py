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
            conn.close()
        logger.info("session_store_initialized", path=str(self._db_path))

    def save_session(self, session_id: str, title: str | None = None, status: str = "active") -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO sessions (session_id, title, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET title=?, status=?, updated_at=?",
                (session_id, title, status, now, now, title, status, now),
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
                "SELECT session_id, title, status, created_at, updated_at "
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
                "event": r[0],
                "data": json.loads(r[1]),
                "timestamp": r[2],
            }
            for r in rows
        ]

    def delete_session(self, session_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
            conn.commit()
            conn.close()
            return cur.rowcount > 0
