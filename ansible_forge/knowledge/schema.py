"""KuzuDB node and edge table definitions for the knowledge graph."""

from __future__ import annotations

NODE_TABLES: list[str] = [
    (
        "CREATE NODE TABLE IF NOT EXISTS Host("
        "hostname STRING, os_family STRING, distribution STRING, "
        "distribution_version STRING, architecture STRING, "
        "kernel STRING, last_seen INT64, "
        "PRIMARY KEY(hostname))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Module("
        "fqcn STRING, doc_summary STRING, "
        "PRIMARY KEY(fqcn))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Task("
        "task_id STRING, name STRING, module_fqcn STRING, role_name STRING, "
        "PRIMARY KEY(task_id))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Role("
        "name STRING, path STRING, "
        "PRIMARY KEY(name))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Playbook("
        "name STRING, path STRING, "
        "PRIMARY KEY(name))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS ErrorPattern("
        "message_hash STRING, message_template STRING, "
        "module STRING, os_family STRING, first_seen INT64, "
        "PRIMARY KEY(message_hash))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Resolution("
        "resolution_id STRING, descr STRING, "
        "action_taken STRING, success BOOL, created_at INT64, "
        "PRIMARY KEY(resolution_id))"
    ),
    (
        "CREATE NODE TABLE IF NOT EXISTS Execution("
        "execution_id STRING, session_id STRING, "
        "timestamp INT64, mode STRING, status STRING, rc INT64, "
        "PRIMARY KEY(execution_id))"
    ),
]

REL_TABLES: list[str] = [
    "CREATE REL TABLE IF NOT EXISTS RAN_TASK(FROM Host TO Task, outcome STRING, ts INT64)",
    "CREATE REL TABLE IF NOT EXISTS USES_MODULE(FROM Task TO Module)",
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO_ROLE(FROM Task TO Role)",
    "CREATE REL TABLE IF NOT EXISTS BELONGS_TO_PLAYBOOK(FROM Task TO Playbook)",
    "CREATE REL TABLE IF NOT EXISTS USED_IN(FROM Role TO Playbook)",
    "CREATE REL TABLE IF NOT EXISTS TARGETS(FROM Execution TO Host)",
    "CREATE REL TABLE IF NOT EXISTS RUNS(FROM Execution TO Playbook)",
    "CREATE REL TABLE IF NOT EXISTS OCCURRED_ON(FROM ErrorPattern TO Host)",
    "CREATE REL TABLE IF NOT EXISTS DURING_TASK(FROM ErrorPattern TO Task)",
    "CREATE REL TABLE IF NOT EXISTS RESOLVES(FROM Resolution TO ErrorPattern)",
    "CREATE REL TABLE IF NOT EXISTS USED_MODULE(FROM Resolution TO Module)",
]

ALL_DDL = NODE_TABLES + REL_TABLES
