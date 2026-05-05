"""Persistent infrastructure store — the agent's memory of your fleet."""

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
CREATE TABLE IF NOT EXISTS hosts (
    host_id TEXT PRIMARY KEY,
    hostname TEXT NOT NULL,
    ip_address TEXT,
    groups_json TEXT NOT NULL DEFAULT '[]',
    vars_json TEXT NOT NULL DEFAULT '{}',
    connection_type TEXT NOT NULL DEFAULT 'ssh',
    ansible_user TEXT,
    status TEXT NOT NULL DEFAULT 'unknown',
    source_id TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS host_facts (
    host_id TEXT PRIMARY KEY,
    facts_json TEXT NOT NULL,
    collected_at REAL NOT NULL,
    FOREIGN KEY (host_id) REFERENCES hosts(host_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS applied_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id TEXT NOT NULL,
    role_name TEXT NOT NULL,
    playbook TEXT NOT NULL,
    session_id TEXT,
    applied_at REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'success',
    FOREIGN KEY (host_id) REFERENCES hosts(host_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_applied_roles_host ON applied_roles(host_id);
CREATE TABLE IF NOT EXISTS run_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    playbook TEXT NOT NULL,
    mode TEXT NOT NULL,
    hosts_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,
    event_count INTEGER NOT NULL DEFAULT 0,
    summary_json TEXT NOT NULL DEFAULT '{}',
    started_at REAL NOT NULL,
    finished_at REAL
);
CREATE INDEX IF NOT EXISTS idx_run_history_session ON run_history(session_id);
CREATE TABLE IF NOT EXISTS drift_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host_id TEXT NOT NULL,
    field TEXT NOT NULL,
    expected_value TEXT,
    actual_value TEXT,
    detected_at REAL NOT NULL,
    resolved_at REAL,
    FOREIGN KEY (host_id) REFERENCES hosts(host_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_drift_host ON drift_records(host_id);
CREATE TABLE IF NOT EXISTS inventory_sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    plugin_type TEXT NOT NULL,
    config_yaml TEXT NOT NULL,
    regions_json TEXT NOT NULL DEFAULT '[]',
    filters_json TEXT NOT NULL DEFAULT '{}',
    last_synced_at REAL,
    host_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'never_synced',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


class InfrastructureStore:
    """Persistent store for infrastructure state — hosts, facts, roles, and run history."""

    _instance: InfrastructureStore | None = None

    def __init__(self, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".ansibleforge" / "infrastructure.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    @classmethod
    def get_instance(cls) -> InfrastructureStore:
        if cls._instance is None:
            cls._instance = InfrastructureStore()
        return cls._instance

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
        logger.info("infrastructure_store_initialized", path=str(self._db_path))

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(hosts)").fetchall()}
        if "source_id" not in cols:
            conn.execute("ALTER TABLE hosts ADD COLUMN source_id TEXT")
            conn.commit()

    # ── Host CRUD ─────────────────────────────────────────────────────

    def upsert_host(
        self,
        hostname: str,
        ip_address: str = "",
        groups: list[str] | None = None,
        variables: dict[str, Any] | None = None,
        connection_type: str = "ssh",
        ansible_user: str = "",
        status: str = "unknown",
        source_id: str | None = None,
    ) -> str:
        host_id = hostname.replace(".", "_").replace(":", "_")
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO hosts (host_id, hostname, ip_address, groups_json, vars_json, "
                "connection_type, ansible_user, status, source_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(host_id) DO UPDATE SET "
                "ip_address=?, groups_json=?, vars_json=?, connection_type=?, "
                "ansible_user=?, status=?, source_id=?, updated_at=?",
                (
                    host_id, hostname, ip_address,
                    json.dumps(groups or []), json.dumps(variables or {}),
                    connection_type, ansible_user, status, source_id, now, now,
                    ip_address, json.dumps(groups or []), json.dumps(variables or {}),
                    connection_type, ansible_user, status, source_id, now,
                ),
            )
            conn.commit()
            conn.close()
        return host_id

    def get_host(self, host_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT host_id, hostname, ip_address, groups_json, vars_json, "
                "connection_type, ansible_user, status, source_id, created_at, updated_at "
                "FROM hosts WHERE host_id=?",
                (host_id,),
            ).fetchone()
            conn.close()
        if not row:
            return None
        return self._host_row_to_dict(row)

    def list_hosts(
        self, group: str | None = None, source_id: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            base = (
                "SELECT host_id, hostname, ip_address, groups_json, vars_json, "
                "connection_type, ansible_user, status, source_id, created_at, updated_at "
                "FROM hosts"
            )
            clauses: list[str] = []
            params: list[Any] = []
            if group:
                clauses.append("groups_json LIKE ?")
                params.append(f'%"{group}"%')
            if source_id is not None:
                clauses.append("source_id = ?")
                params.append(source_id)
            where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(f"{base}{where} ORDER BY hostname", params).fetchall()
            conn.close()
        return [self._host_row_to_dict(r) for r in rows]

    def delete_host(self, host_id: str) -> bool:
        with self._lock:
            conn = self._connect()
            cur = conn.execute("DELETE FROM hosts WHERE host_id=?", (host_id,))
            conn.commit()
            conn.close()
            return cur.rowcount > 0

    def update_host_status(self, host_id: str, status: str) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE hosts SET status=?, updated_at=? WHERE host_id=?",
                (status, now, host_id),
            )
            conn.commit()
            conn.close()

    # ── Facts ─────────────────────────────────────────────────────────

    def save_facts(self, host_id: str, facts: dict[str, Any]) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO host_facts (host_id, facts_json, collected_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(host_id) DO UPDATE SET facts_json=?, collected_at=?",
                (host_id, json.dumps(facts), now, json.dumps(facts), now),
            )
            conn.commit()
            conn.close()

    def get_facts(self, host_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT facts_json, collected_at FROM host_facts WHERE host_id=?",
                (host_id,),
            ).fetchone()
            conn.close()
        if not row:
            return None
        return {**json.loads(row[0]), "_collected_at": row[1]}

    def get_all_facts(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT host_id, facts_json, collected_at FROM host_facts"
            ).fetchall()
            conn.close()
        return {
            r[0]: {**json.loads(r[1]), "_collected_at": r[2]}
            for r in rows
        }

    # ── Applied roles ──────────────────────────────────────────────────

    def record_applied_role(
        self,
        host_id: str,
        role_name: str,
        playbook: str,
        session_id: str = "",
        status: str = "success",
    ) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO applied_roles (host_id, role_name, playbook, session_id, applied_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (host_id, role_name, playbook, session_id, now, status),
            )
            conn.commit()
            conn.close()

    def get_applied_roles(self, host_id: str) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT role_name, playbook, session_id, applied_at, status "
                "FROM applied_roles WHERE host_id=? ORDER BY applied_at DESC LIMIT 50",
                (host_id,),
            ).fetchall()
            conn.close()
        return [
            {
                "role_name": r[0],
                "playbook": r[1],
                "session_id": r[2],
                "applied_at": r[3],
                "status": r[4],
            }
            for r in rows
        ]

    # ── Run history ────────────────────────────────────────────────────

    def record_run(
        self,
        session_id: str,
        playbook: str,
        mode: str,
        hosts: list[str],
        status: str,
        event_count: int = 0,
        summary: dict[str, Any] | None = None,
    ) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO run_history (session_id, playbook, mode, hosts_json, status, "
                "event_count, summary_json, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id, playbook, mode, json.dumps(hosts),
                    status, event_count, json.dumps(summary or {}), now, now,
                ),
            )
            run_id = cur.lastrowid
            conn.commit()
            conn.close()
        return run_id or 0

    def update_run(
        self,
        run_id: int,
        status: str,
        hosts: list[str] | None = None,
        event_count: int | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            parts = ["status=?", "finished_at=?"]
            params: list[Any] = [status, now]
            if hosts is not None:
                parts.append("hosts_json=?")
                params.append(json.dumps(hosts))
            if event_count is not None:
                parts.append("event_count=?")
                params.append(event_count)
            if summary is not None:
                parts.append("summary_json=?")
                params.append(json.dumps(summary))
            params.append(run_id)
            conn.execute(f"UPDATE run_history SET {', '.join(parts)} WHERE id=?", params)
            conn.commit()
            conn.close()

    def list_runs(self, limit: int = 50, session_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            if session_id:
                rows = conn.execute(
                    "SELECT id, session_id, playbook, mode, hosts_json, status, "
                    "event_count, summary_json, started_at, finished_at "
                    "FROM run_history WHERE session_id=? ORDER BY started_at DESC LIMIT ?",
                    (session_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, session_id, playbook, mode, hosts_json, status, "
                    "event_count, summary_json, started_at, finished_at "
                    "FROM run_history ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            conn.close()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "playbook": r[2],
                "mode": r[3],
                "hosts": json.loads(r[4]),
                "status": r[5],
                "event_count": r[6],
                "summary": json.loads(r[7]),
                "started_at": r[8],
                "finished_at": r[9],
            }
            for r in rows
        ]

    # ── Drift detection ────────────────────────────────────────────────

    def record_drift(
        self,
        host_id: str,
        field: str,
        expected_value: str,
        actual_value: str,
    ) -> int:
        now = time.time()
        with self._lock:
            conn = self._connect()
            cur = conn.execute(
                "INSERT INTO drift_records (host_id, field, expected_value, actual_value, detected_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (host_id, field, expected_value, actual_value, now),
            )
            drift_id = cur.lastrowid
            conn.commit()
            conn.close()
        return drift_id or 0

    def get_unresolved_drift(self, host_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            if host_id:
                rows = conn.execute(
                    "SELECT id, host_id, field, expected_value, actual_value, detected_at "
                    "FROM drift_records WHERE host_id=? AND resolved_at IS NULL "
                    "ORDER BY detected_at DESC",
                    (host_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT id, host_id, field, expected_value, actual_value, detected_at "
                    "FROM drift_records WHERE resolved_at IS NULL "
                    "ORDER BY detected_at DESC",
                ).fetchall()
            conn.close()
        return [
            {
                "id": r[0],
                "host_id": r[1],
                "field": r[2],
                "expected_value": r[3],
                "actual_value": r[4],
                "detected_at": r[5],
            }
            for r in rows
        ]

    def resolve_drift(self, drift_id: int) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE drift_records SET resolved_at=? WHERE id=?",
                (now, drift_id),
            )
            conn.commit()
            conn.close()

    def detect_drift(self, host_id: str, new_facts: dict[str, Any]) -> list[dict[str, str]]:
        old_facts_record = self.get_facts(host_id)
        if not old_facts_record:
            return []

        old_facts = {k: v for k, v in old_facts_record.items() if not k.startswith("_")}
        drifts: list[dict[str, str]] = []
        tracked_fields = (
            "distribution", "distribution_version", "kernel", "pkg_mgr",
            "service_mgr", "selinux", "architecture", "python_version",
        )
        for field in tracked_fields:
            old_val = str(old_facts.get(field, ""))
            new_val = str(new_facts.get(field, ""))
            if old_val and new_val and old_val != new_val:
                self.record_drift(host_id, field, old_val, new_val)
                drifts.append({
                    "field": field,
                    "expected": old_val,
                    "actual": new_val,
                })
        return drifts

    # ── Inventory sources ───────────────────────────────────────────────

    def upsert_source(
        self,
        source_id: str,
        name: str,
        plugin_type: str,
        config_yaml: str,
        regions: list[str] | None = None,
        filters: dict[str, Any] | None = None,
    ) -> str:
        now = time.time()
        with self._lock:
            conn = self._connect()
            conn.execute(
                "INSERT INTO inventory_sources "
                "(source_id, name, plugin_type, config_yaml, regions_json, filters_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(source_id) DO UPDATE SET "
                "name=?, plugin_type=?, config_yaml=?, regions_json=?, filters_json=?, updated_at=?",
                (
                    source_id, name, plugin_type, config_yaml,
                    json.dumps(regions or []), json.dumps(filters or {}), now, now,
                    name, plugin_type, config_yaml,
                    json.dumps(regions or []), json.dumps(filters or {}), now,
                ),
            )
            conn.commit()
            conn.close()
        return source_id

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with self._lock:
            conn = self._connect()
            row = conn.execute(
                "SELECT source_id, name, plugin_type, config_yaml, regions_json, "
                "filters_json, last_synced_at, host_count, status, created_at, updated_at "
                "FROM inventory_sources WHERE source_id=?",
                (source_id,),
            ).fetchone()
            conn.close()
        if not row:
            return None
        return self._source_row_to_dict(row)

    def list_sources(self) -> list[dict[str, Any]]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT source_id, name, plugin_type, config_yaml, regions_json, "
                "filters_json, last_synced_at, host_count, status, created_at, updated_at "
                "FROM inventory_sources ORDER BY name",
            ).fetchall()
            conn.close()
        return [self._source_row_to_dict(r) for r in rows]

    def delete_source(self, source_id: str, remove_hosts: bool = False) -> bool:
        with self._lock:
            conn = self._connect()
            if remove_hosts:
                conn.execute("DELETE FROM hosts WHERE source_id=?", (source_id,))
            else:
                conn.execute(
                    "UPDATE hosts SET source_id=NULL WHERE source_id=?", (source_id,),
                )
            cur = conn.execute(
                "DELETE FROM inventory_sources WHERE source_id=?", (source_id,),
            )
            conn.commit()
            conn.close()
            return cur.rowcount > 0

    def update_source_sync_status(
        self,
        source_id: str,
        status: str,
        host_count: int | None = None,
    ) -> None:
        now = time.time()
        with self._lock:
            conn = self._connect()
            if host_count is not None:
                conn.execute(
                    "UPDATE inventory_sources SET status=?, host_count=?, "
                    "last_synced_at=?, updated_at=? WHERE source_id=?",
                    (status, host_count, now, now, source_id),
                )
            else:
                conn.execute(
                    "UPDATE inventory_sources SET status=?, updated_at=? WHERE source_id=?",
                    (status, now, source_id),
                )
            conn.commit()
            conn.close()

    def purge_stale_hosts(self, source_id: str, current_hostnames: set[str]) -> int:
        existing = self.list_hosts(source_id=source_id)
        removed = 0
        for h in existing:
            if h["hostname"] not in current_hostnames:
                self.delete_host(h["host_id"])
                removed += 1
        return removed

    @staticmethod
    def _source_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "source_id": row[0],
            "name": row[1],
            "plugin_type": row[2],
            "config_yaml": row[3],
            "regions": json.loads(row[4]),
            "filters": json.loads(row[5]),
            "last_synced_at": row[6],
            "host_count": row[7],
            "status": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }

    # ── Context for the agent ──────────────────────────────────────────

    def build_infrastructure_context(self) -> str:
        hosts = self.list_hosts()
        if not hosts:
            return ""

        sources = self.list_sources()
        source_names = {s["source_id"]: s["name"] for s in sources}

        lines = ["Known infrastructure:"]
        if sources:
            lines.append(f"  Inventory sources: {', '.join(s['name'] for s in sources)}")
        for h in hosts:
            groups = ", ".join(h["groups"]) if h["groups"] else "ungrouped"
            status = h["status"]
            line = f"  {h['hostname']}"
            if h["ip_address"]:
                line += f" ({h['ip_address']})"
            line += f" [{groups}] status={status}"
            src = source_names.get(h.get("source_id") or "")
            if src:
                line += f" source={src}"
            lines.append(line)

        all_facts = self.get_all_facts()
        if all_facts:
            lines.append("\nHost details:")
            for host_id, facts in all_facts.items():
                distro = facts.get("distribution", "?")
                version = facts.get("distribution_version", "")
                arch = facts.get("architecture", "")
                pkg = facts.get("pkg_mgr", "?")
                svc = facts.get("service_mgr", "?")
                mem = facts.get("memory_mb", 0)
                ram = f"{mem}MB" if mem else "?"
                lines.append(
                    f"  {host_id}: {distro} {version}, {arch}, {pkg}, {svc}, {ram} RAM"
                )

        drifts = self.get_unresolved_drift()
        if drifts:
            lines.append(f"\nDrift warnings ({len(drifts)} unresolved):")
            for d in drifts[:5]:
                lines.append(
                    f"  {d['host_id']}.{d['field']}: "
                    f"expected={d['expected_value']}, actual={d['actual_value']}"
                )

        recent_runs = self.list_runs(limit=5)
        if recent_runs:
            lines.append("\nRecent runs:")
            for r in recent_runs:
                hosts_str = ", ".join(r["hosts"][:3])
                lines.append(
                    f"  {r['playbook']} ({r['mode']}) -> {r['status']} "
                    f"on [{hosts_str}]"
                )

        return "\n".join(lines)

    # ── Stats ──────────────────────────────────────────────────────────

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            conn = self._connect()
            host_count = conn.execute("SELECT COUNT(*) FROM hosts").fetchone()[0]
            facts_count = conn.execute("SELECT COUNT(*) FROM host_facts").fetchone()[0]
            run_count = conn.execute("SELECT COUNT(*) FROM run_history").fetchone()[0]
            drift_count = conn.execute(
                "SELECT COUNT(*) FROM drift_records WHERE resolved_at IS NULL"
            ).fetchone()[0]
            source_count = conn.execute(
                "SELECT COUNT(*) FROM inventory_sources"
            ).fetchone()[0]
            conn.close()
        return {
            "hosts": host_count,
            "hosts_with_facts": facts_count,
            "total_runs": run_count,
            "unresolved_drifts": drift_count,
            "inventory_sources": source_count,
        }

    @staticmethod
    def _host_row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "host_id": row[0],
            "hostname": row[1],
            "ip_address": row[2],
            "groups": json.loads(row[3]),
            "variables": json.loads(row[4]),
            "connection_type": row[5],
            "ansible_user": row[6],
            "status": row[7],
            "source_id": row[8],
            "created_at": row[9],
            "updated_at": row[10],
        }
