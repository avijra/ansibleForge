"""Generate rollback playbooks for destructive operations."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import ToolResult

logger = get_logger(__name__)

DESTRUCTIVE_MODULES = frozenset({
    "ansible.builtin.file",
    "ansible.builtin.user",
    "ansible.builtin.group",
    "ansible.builtin.service",
    "ansible.builtin.systemd",
    "ansible.builtin.cron",
    "ansible.builtin.iptables",
    "ansible.builtin.command",
    "ansible.builtin.shell",
    "ansible.builtin.raw",
    "ansible.builtin.reboot",
})


class RollbackPlanner:
    """Analyzes a playbook and generates a best-effort rollback playbook."""

    def generate(self, workspace_path: str, playbook_name: str) -> ToolResult:
        playbook_path = Path(workspace_path) / "project" / playbook_name
        if not playbook_path.exists():
            return ToolResult.fail(f"Playbook not found: {playbook_path}")

        try:
            plays = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            return ToolResult.fail(f"Failed to parse playbook: {exc}")

        if not isinstance(plays, list):
            return ToolResult.fail("Playbook is not a valid YAML list of plays")

        rollback_plays = []
        for play in plays:
            rollback_tasks = self._generate_rollback_tasks(play.get("tasks", []))
            if rollback_tasks:
                rollback_plays.append({
                    "name": f"ROLLBACK: {play.get('name', 'unnamed')}",
                    "hosts": play.get("hosts", "all"),
                    "become": play.get("become", False),
                    "tasks": list(reversed(rollback_tasks)),
                })

        if not rollback_plays:
            return ToolResult.ok(
                output="No destructive tasks found — rollback playbook not needed.",
                rollback_needed=False,
            )

        rollback_name = f"rollback_{playbook_name}"
        rollback_path = Path(workspace_path) / "project" / rollback_name
        rollback_path.write_text(
            yaml.dump(rollback_plays, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )

        return ToolResult.ok(
            output=f"Rollback playbook generated: {rollback_path}",
            path=str(rollback_path),
            rollback_needed=True,
            task_count=sum(len(p["tasks"]) for p in rollback_plays),
        )

    def _generate_rollback_tasks(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rollback_tasks: list[dict[str, Any]] = []

        for task in tasks:
            module = self._detect_module(task)
            if not module:
                continue

            rollback = self._create_rollback_task(task, module)
            if rollback:
                rollback_tasks.append(rollback)

        return rollback_tasks

    @staticmethod
    def _detect_module(task: dict[str, Any]) -> str | None:
        for key in task:
            if key in DESTRUCTIVE_MODULES or "." in key:
                return key
        return None

    @staticmethod
    def _create_rollback_task(task: dict[str, Any], module: str) -> dict[str, Any] | None:
        """Create a reverse task where possible."""
        task_name = task.get("name", "unnamed")
        params = task.get(module, {})

        if module == "ansible.builtin.service" and isinstance(params, dict):
            state = params.get("state")
            reverse_state = {"started": "stopped", "stopped": "started"}.get(state or "")
            if reverse_state:
                return {
                    "name": f"Rollback: {task_name}",
                    module: {**params, "state": reverse_state},
                }

        if module == "ansible.builtin.file" and isinstance(params, dict):
            state = params.get("state")
            if state in ("directory", "touch"):
                return {
                    "name": f"Rollback: remove {params.get('path', '')}",
                    module: {"path": params.get("path"), "state": "absent"},
                }

        if module in ("ansible.builtin.user", "ansible.builtin.group") and isinstance(params, dict):
            state = params.get("state", "present")
            if state == "present":
                return {
                    "name": f"Rollback: remove {params.get('name', '')}",
                    module: {"name": params.get("name"), "state": "absent"},
                }

        if module in DESTRUCTIVE_MODULES:
            return {
                "name": f"MANUAL ROLLBACK NEEDED: {task_name}",
                "ansible.builtin.debug": {
                    "msg": f"Task '{task_name}' using '{module}' may need manual rollback."
                },
            }

        return None
