"""KuzuDB-backed knowledge graph with lazy initialisation."""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

import kuzu

from ansible_forge.knowledge.schema import ALL_DDL
from ansible_forge.logging import get_logger

logger = get_logger(__name__)


class KnowledgeGraph:
    """Thin wrapper around a KuzuDB database with schema bootstrapping.

    The database is opened lazily on first use so importing this module
    has no side effects.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db: kuzu.Database | None = None
        self._lock = threading.Lock()

    def _ensure_open(self) -> kuzu.Database:
        if self._db is not None:
            return self._db
        with self._lock:
            if self._db is not None:
                return self._db
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = kuzu.Database(str(self._db_path))
            self._bootstrap_schema()
            logger.info("knowledge_graph_opened", path=str(self._db_path))
            return self._db

    def _bootstrap_schema(self) -> None:
        conn = kuzu.Connection(self._db)
        for ddl in ALL_DDL:
            with contextlib.suppress(RuntimeError):
                conn.execute(ddl)

    def _conn(self) -> kuzu.Connection:
        return kuzu.Connection(self._ensure_open())

    def execute(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        conn = self._conn()
        result = conn.execute(cypher, parameters=params or {})
        rows: list[list[Any]] = []
        while result.has_next():
            rows.append(result.get_next())
        return rows

    def merge_host(
        self,
        hostname: str,
        os_family: str = "",
        distribution: str = "",
        distribution_version: str = "",
        architecture: str = "",
        kernel: str = "",
        last_seen: int = 0,
    ) -> None:
        self.execute(
            "MERGE (h:Host {hostname: $hostname}) "
            "SET h.os_family = $os_family, h.distribution = $distribution, "
            "h.distribution_version = $dist_ver, h.architecture = $arch, "
            "h.kernel = $kernel, h.last_seen = $last_seen",
            {
                "hostname": hostname,
                "os_family": os_family,
                "distribution": distribution,
                "dist_ver": distribution_version,
                "arch": architecture,
                "kernel": kernel,
                "last_seen": last_seen,
            },
        )

    def merge_module(self, fqcn: str, doc_summary: str = "") -> None:
        self.execute(
            "MERGE (m:Module {fqcn: $fqcn}) SET m.doc_summary = $doc",
            {"fqcn": fqcn, "doc": doc_summary},
        )

    def merge_task(
        self, task_id: str, name: str, module_fqcn: str = "", role_name: str = ""
    ) -> None:
        self.execute(
            "MERGE (t:Task {task_id: $tid}) "
            "SET t.name = $name, t.module_fqcn = $mod, t.role_name = $role",
            {"tid": task_id, "name": name, "mod": module_fqcn, "role": role_name},
        )

    def merge_role(self, name: str, path: str = "") -> None:
        self.execute(
            "MERGE (r:Role {name: $name}) SET r.path = $path",
            {"name": name, "path": path},
        )

    def merge_playbook(self, name: str, path: str = "") -> None:
        self.execute(
            "MERGE (p:Playbook {name: $name}) SET p.path = $path",
            {"name": name, "path": path},
        )

    def merge_error_pattern(
        self,
        message_hash: str,
        message_template: str,
        module: str = "",
        os_family: str = "",
        first_seen: int = 0,
    ) -> None:
        self.execute(
            "MERGE (e:ErrorPattern {message_hash: $mhash}) "
            "SET e.message_template = $tmpl, e.module = $mod, "
            "e.os_family = $os, e.first_seen = $ts",
            {
                "mhash": message_hash,
                "tmpl": message_template,
                "mod": module,
                "os": os_family,
                "ts": first_seen,
            },
        )

    def create_execution(
        self,
        execution_id: str,
        session_id: str,
        timestamp: int,
        mode: str,
        status: str,
        rc: int,
    ) -> None:
        self.execute(
            "CREATE (e:Execution {execution_id: $eid, session_id: $sid, "
            "timestamp: $ts, mode: $mode, status: $status, rc: $rc})",
            {
                "eid": execution_id,
                "sid": session_id,
                "ts": timestamp,
                "mode": mode,
                "status": status,
                "rc": rc,
            },
        )

    def create_resolution(
        self,
        resolution_id: str,
        description: str,
        action_taken: str,
        success: bool,
        created_at: int,
    ) -> None:
        self.execute(
            "CREATE (r:Resolution {resolution_id: $rid, descr: $descr_val, "
            "action_taken: $action, success: $ok, created_at: $ts})",
            {
                "rid": resolution_id,
                "descr_val": description,
                "action": action_taken,
                "ok": success,
                "ts": created_at,
            },
        )

    def link_ran_task(self, hostname: str, task_id: str, outcome: str, ts: int) -> None:
        self.execute(
            "MATCH (h:Host {hostname: $host}), (t:Task {task_id: $tid}) "
            "CREATE (h)-[:RAN_TASK {outcome: $out, ts: $ts}]->(t)",
            {"host": hostname, "tid": task_id, "out": outcome, "ts": ts},
        )

    def link_uses_module(self, task_id: str, fqcn: str) -> None:
        self.execute(
            "MATCH (t:Task {task_id: $tid}), (m:Module {fqcn: $fqcn}) "
            "CREATE (t)-[:USES_MODULE]->(m)",
            {"tid": task_id, "fqcn": fqcn},
        )

    def link_execution_targets(self, execution_id: str, hostname: str) -> None:
        self.execute(
            "MATCH (e:Execution {execution_id: $eid}), (h:Host {hostname: $host}) "
            "CREATE (e)-[:TARGETS]->(h)",
            {"eid": execution_id, "host": hostname},
        )

    def link_execution_runs(self, execution_id: str, playbook_name: str) -> None:
        self.execute(
            "MATCH (e:Execution {execution_id: $eid}), (p:Playbook {name: $pname}) "
            "CREATE (e)-[:RUNS]->(p)",
            {"eid": execution_id, "pname": playbook_name},
        )

    def link_error_occurred_on(self, message_hash: str, hostname: str) -> None:
        self.execute(
            "MATCH (e:ErrorPattern {message_hash: $mhash}), (h:Host {hostname: $host}) "
            "CREATE (e)-[:OCCURRED_ON]->(h)",
            {"mhash": message_hash, "host": hostname},
        )

    def link_error_during_task(self, message_hash: str, task_id: str) -> None:
        self.execute(
            "MATCH (e:ErrorPattern {message_hash: $mhash}), (t:Task {task_id: $tid}) "
            "CREATE (e)-[:DURING_TASK]->(t)",
            {"mhash": message_hash, "tid": task_id},
        )

    def link_resolution_resolves(self, resolution_id: str, message_hash: str) -> None:
        self.execute(
            "MATCH (r:Resolution {resolution_id: $rid}), (e:ErrorPattern {message_hash: $mhash}) "
            "CREATE (r)-[:RESOLVES]->(e)",
            {"rid": resolution_id, "mhash": message_hash},
        )

    def query_errors_for_module(self, module_fqcn: str, limit: int = 10) -> list[list[Any]]:
        return self.execute(
            "MATCH (e:ErrorPattern) WHERE e.module = $mod "
            "OPTIONAL MATCH (r:Resolution)-[:RESOLVES]->(e) "
            "RETURN e.message_template, e.os_family, r.descr, r.success "
            "LIMIT $lim",
            {"mod": module_fqcn, "lim": limit},
        )

    def query_host_history(self, hostname: str, limit: int = 20) -> list[list[Any]]:
        return self.execute(
            "MATCH (h:Host {hostname: $host})-[r:RAN_TASK]->(t:Task) "
            "RETURN t.name, t.module_fqcn, r.outcome, r.ts "
            "ORDER BY r.ts DESC LIMIT $lim",
            {"host": hostname, "lim": limit},
        )

    def query_recent_errors(self, limit: int = 10) -> list[list[Any]]:
        return self.execute(
            "MATCH (e:ErrorPattern) "
            "OPTIONAL MATCH (r:Resolution)-[:RESOLVES]->(e) "
            "RETURN e.message_template, e.module, e.os_family, "
            "r.descr, r.success "
            "ORDER BY e.first_seen DESC LIMIT $lim",
            {"lim": limit},
        )

    def query_host_info(self, hostname: str) -> list[list[Any]]:
        return self.execute(
            "MATCH (h:Host {hostname: $host}) "
            "RETURN h.os_family, h.distribution, h.architecture",
            {"host": hostname},
        )

    def node_count(self, label: str) -> int:
        rows = self.execute(f"MATCH (n:{label}) RETURN count(n)")
        return rows[0][0] if rows else 0

    def close(self) -> None:
        with self._lock:
            self._db = None
