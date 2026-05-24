"""Score playbook risk based on YAML content and check-mode results."""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_DESTRUCTIVE_STATES = {"absent", "stopped", "removed", "purged", "killed", "dead"}

_DESTRUCTIVE_MODULES = frozenset({
    "ansible.builtin.file",
    "ansible.builtin.user",
    "ansible.builtin.group",
    "ansible.builtin.mount",
    "ansible.builtin.lvg",
    "ansible.builtin.lvol",
    "ansible.builtin.iptables",
    "ansible.posix.firewalld",
    "community.general.ufw",
    "file", "user", "group", "mount", "lvg", "lvol",
    "iptables", "firewalld", "ufw",
})

_SHELL_MODULES = frozenset({
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.builtin.raw",
    "ansible.builtin.script",
    "command", "shell", "raw", "script",
})

_SERVICE_MODULES = frozenset({
    "ansible.builtin.service",
    "ansible.builtin.systemd",
    "ansible.builtin.sysvinit",
    "service", "systemd", "sysvinit",
})

_RM_PATTERN = re.compile(r"\brm\s+-[a-zA-Z]*[rf]", re.IGNORECASE)


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


def score_playbook_risk(
    playbook_path: Path,
    check_result_data: dict[str, Any] | None = None,
) -> RiskLevel:
    """Analyze playbook YAML and optional check-mode results to assign risk."""
    try:
        content = playbook_path.read_text()
        plays = yaml.safe_load(content)
    except Exception:
        logger.warning("risk_scorer_parse_failure", path=str(playbook_path))
        return RiskLevel.MEDIUM

    if not isinstance(plays, list):
        return RiskLevel.MEDIUM

    has_destructive = False
    has_shell = False
    has_service_change = False
    host_count = 0

    for play in plays:
        if not isinstance(play, dict):
            continue

        hosts = play.get("hosts", "")
        if hosts == "all":
            host_count = max(host_count, 100)
        elif isinstance(hosts, str) and "," in hosts:
            host_count = max(host_count, hosts.count(",") + 1)
        else:
            host_count = max(host_count, 1)

        tasks = _collect_tasks(play)
        for task in tasks:
            if not isinstance(task, dict):
                continue

            module = _extract_module(task)
            if not module:
                continue

            task_args = task.get(module) or {}
            if isinstance(task_args, str):
                task_args_str = task_args
            elif isinstance(task_args, dict):
                task_args_str = str(task_args)
            else:
                task_args_str = ""

            if module in _DESTRUCTIVE_MODULES:
                state = task_args.get("state", "") if isinstance(task_args, dict) else ""
                if state in _DESTRUCTIVE_STATES:
                    has_destructive = True
                elif "state=" in task_args_str:
                    for ds in _DESTRUCTIVE_STATES:
                        if f"state={ds}" in task_args_str:
                            has_destructive = True
                            break

            if module in _SHELL_MODULES:
                has_shell = True
                if _RM_PATTERN.search(task_args_str):
                    has_destructive = True

            if module in _SERVICE_MODULES:
                state = task_args.get("state", "") if isinstance(task_args, dict) else ""
                if state in ("stopped", "restarted", "reloaded"):
                    has_service_change = True

    if check_result_data:
        change_count = check_result_data.get("change_count", 0)
        has_failures = check_result_data.get("has_failures", False)
        if has_failures:
            return RiskLevel.HIGH
        if change_count > 20:
            host_count = max(host_count, change_count)

    if has_destructive and host_count > 10:
        return RiskLevel.CRITICAL
    if has_destructive:
        return RiskLevel.HIGH
    if has_service_change or has_shell:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def _collect_tasks(play: dict[str, Any]) -> list[dict[str, Any]]:
    """Gather tasks from tasks, pre_tasks, post_tasks, handlers, and role tasks."""
    result: list[dict[str, Any]] = []
    for key in ("tasks", "pre_tasks", "post_tasks", "handlers"):
        items = play.get(key, [])
        if isinstance(items, list):
            result.extend(items)
    roles = play.get("roles", [])
    if isinstance(roles, list):
        for role in roles:
            if isinstance(role, dict) and "tasks_from" in role:
                result.append(role)
    return result


_KNOWN_TASK_KEYS = frozenset({
    "name", "when", "register", "tags", "notify", "become", "become_user",
    "changed_when", "failed_when", "ignore_errors", "loop", "with_items",
    "with_dict", "with_fileglob", "vars", "environment", "block", "rescue",
    "always", "delegate_to", "run_once", "no_log", "retries", "delay",
    "until", "listen", "check_mode", "diff", "timeout", "throttle",
    "collections", "module_defaults", "any_errors_fatal",
})


def _extract_module(task: dict[str, Any]) -> str | None:
    """Return the module name from a task dict."""
    for key in task:
        if key not in _KNOWN_TASK_KEYS and not key.startswith("_"):
            return key
    return None
