"""Manage scheduled/recurring playbook runs with a lightweight in-process scheduler."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS schedules (
    schedule_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    workspace_path TEXT NOT NULL,
    playbook TEXT NOT NULL,
    inventory TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    host_limit TEXT DEFAULT '',
    extra_vars_json TEXT DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run_at REAL,
    next_run_at REAL,
    run_count INTEGER NOT NULL DEFAULT 0,
    last_status TEXT DEFAULT '',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def _parse_cron_field(field: str, min_val: int, max_val: int) -> list[int]:
    if field == "*":
        return list(range(min_val, max_val + 1))

    values: list[int] = []
    for part in field.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            start = min_val if base == "*" else int(base)
            for i in range(start, max_val + 1, int(step)):
                values.append(i)
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.extend(range(int(lo), int(hi) + 1))
        else:
            values.append(int(part))
    return sorted(set(v for v in values if min_val <= v <= max_val))


def cron_next_run(expression: str, after: float | None = None) -> float | None:
    """Calculate next run timestamp from a 5-field cron expression (min hour dom month dow)."""
    parts = expression.strip().split()
    if len(parts) != 5:
        return None

    try:
        minutes = _parse_cron_field(parts[0], 0, 59)
        hours = _parse_cron_field(parts[1], 0, 23)
        doms = _parse_cron_field(parts[2], 1, 31)
        months = _parse_cron_field(parts[3], 1, 12)
        dows = _parse_cron_field(parts[4], 0, 6)
    except (ValueError, IndexError):
        return None

    import datetime

    now = datetime.datetime.fromtimestamp(after or time.time())
    candidate = now.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)

    for _ in range(525960):
        if (
            candidate.month in months
            and candidate.day in doms
            and candidate.weekday() in dows  # Python: Mon=0, cron: Sun=0
            and candidate.hour in hours
            and candidate.minute in minutes
        ):
            return candidate.timestamp()
        candidate += datetime.timedelta(minutes=1)

    return None


class ScheduleStore:
    _instance: ScheduleStore | None = None
    _lock = threading.Lock()

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or str(
            Path.home() / ".ansibleforge" / "schedules.db"
        )
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.executescript(_CREATE_SQL)
        conn.close()

    @classmethod
    def get_instance(cls) -> ScheduleStore:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def create(self, schedule: dict[str, Any]) -> str:
        sid = str(uuid.uuid4())[:8]
        now = time.time()
        next_run = cron_next_run(schedule.get("cron_expression", ""))

        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "INSERT INTO schedules (schedule_id, name, workspace_path, playbook, "
            "inventory, cron_expression, host_limit, extra_vars_json, enabled, "
            "next_run_at, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                schedule.get("name", ""),
                schedule.get("workspace_path", ""),
                schedule.get("playbook", ""),
                schedule.get("inventory", ""),
                schedule.get("cron_expression", ""),
                schedule.get("host_limit", ""),
                json.dumps(schedule.get("extra_vars", {})),
                1,
                next_run,
                now,
                now,
            ),
        )
        conn.commit()
        conn.close()
        return sid

    def list_all(self) -> list[dict[str, Any]]:
        conn = sqlite3.connect(self._db_path)
        rows = conn.execute(
            "SELECT schedule_id, name, workspace_path, playbook, inventory, "
            "cron_expression, host_limit, enabled, last_run_at, next_run_at, "
            "run_count, last_status, created_at FROM schedules ORDER BY created_at DESC"
        ).fetchall()
        conn.close()
        return [
            {
                "schedule_id": r[0], "name": r[1], "workspace_path": r[2],
                "playbook": r[3], "inventory": r[4], "cron_expression": r[5],
                "host_limit": r[6], "enabled": bool(r[7]), "last_run_at": r[8],
                "next_run_at": r[9], "run_count": r[10], "last_status": r[11],
                "created_at": r[12],
            }
            for r in rows
        ]

    def delete(self, schedule_id: str) -> bool:
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute("DELETE FROM schedules WHERE schedule_id=?", (schedule_id,))
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    def toggle(self, schedule_id: str, enabled: bool) -> bool:
        now = time.time()
        conn = sqlite3.connect(self._db_path)
        cur = conn.execute(
            "UPDATE schedules SET enabled=?, updated_at=? WHERE schedule_id=?",
            (1 if enabled else 0, now, schedule_id),
        )
        conn.commit()
        conn.close()
        return cur.rowcount > 0

    def record_run(self, schedule_id: str, status: str) -> None:
        now = time.time()
        conn = sqlite3.connect(self._db_path)
        row = conn.execute(
            "SELECT cron_expression FROM schedules WHERE schedule_id=?",
            (schedule_id,),
        ).fetchone()
        next_run = cron_next_run(row[0], now) if row else None
        conn.execute(
            "UPDATE schedules SET last_run_at=?, last_status=?, run_count=run_count+1, "
            "next_run_at=?, updated_at=? WHERE schedule_id=?",
            (now, status, next_run, now, schedule_id),
        )
        conn.commit()
        conn.close()


class ScheduleManager(BaseTool):
    @property
    def name(self) -> str:
        return "manage_schedule"

    @property
    def description(self) -> str:
        return (
            "Create, list, enable/disable, or delete scheduled playbook runs. "
            "Schedules use 5-field cron expressions (minute hour day-of-month month day-of-week). "
            "Scheduled runs execute automatically in the background and results appear in run history."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "delete", "enable", "disable"],
                    "description": "Schedule management action",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name for the schedule (for 'create')",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to workspace directory (for 'create')",
                },
                "playbook": {
                    "type": "string",
                    "description": "Playbook filename to run (for 'create')",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename (for 'create')",
                },
                "cron_expression": {
                    "type": "string",
                    "description": (
                        "5-field cron expression (e.g. '0 2 * * *' for daily at 2AM, "
                        "'*/30 * * * *' for every 30 minutes, '0 0 * * 0' for weekly Sunday midnight)"
                    ),
                },
                "host_limit": {
                    "type": "string",
                    "description": "Limit execution to specific hosts/groups (optional)",
                },
                "schedule_id": {
                    "type": "string",
                    "description": "Schedule ID (for 'delete', 'enable', 'disable')",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        workspace_path: str = "",
        playbook: str = "",
        inventory: str = "",
        cron_expression: str = "",
        host_limit: str = "",
        schedule_id: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not action:
            return ToolResult.fail("action is required")

        store = ScheduleStore.get_instance()

        if action == "create":
            if not all([name, workspace_path, playbook, inventory, cron_expression]):
                return ToolResult.fail(
                    "name, workspace_path, playbook, inventory, and cron_expression are required for create"
                )
            next_run = cron_next_run(cron_expression)
            if next_run is None:
                return ToolResult.fail(
                    f"Invalid cron expression: '{cron_expression}'. "
                    "Use 5 fields: minute hour day-of-month month day-of-week"
                )
            sid = store.create({
                "name": name,
                "workspace_path": workspace_path,
                "playbook": playbook,
                "inventory": inventory,
                "cron_expression": cron_expression,
                "host_limit": host_limit,
            })
            import datetime
            next_dt = datetime.datetime.fromtimestamp(next_run).strftime("%Y-%m-%d %H:%M")
            return ToolResult.ok(
                output=f"Schedule '{name}' created (ID: {sid}). Next run: {next_dt}",
                schedule_id=sid,
                next_run=next_dt,
            )

        if action == "list":
            schedules = store.list_all()
            return ToolResult.ok(
                output=f"{len(schedules)} schedule(s) configured",
                schedules=schedules,
            )

        if action == "delete":
            if not schedule_id:
                return ToolResult.fail("schedule_id is required for delete")
            if store.delete(schedule_id):
                return ToolResult.ok(output=f"Schedule {schedule_id} deleted")
            return ToolResult.fail(f"Schedule {schedule_id} not found")

        if action in ("enable", "disable"):
            if not schedule_id:
                return ToolResult.fail(f"schedule_id is required for {action}")
            enabled = action == "enable"
            if store.toggle(schedule_id, enabled):
                return ToolResult.ok(output=f"Schedule {schedule_id} {'enabled' if enabled else 'disabled'}")
            return ToolResult.fail(f"Schedule {schedule_id} not found")

        return ToolResult.fail(f"Unknown action: {action}")
