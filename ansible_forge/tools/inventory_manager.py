"""Create and manage Ansible inventory files (INI and YAML formats)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ansible_forge.tools.base import BaseTool, ToolResult


class InventoryManager(BaseTool):
    @property
    def name(self) -> str:
        return "manage_inventory"

    @property
    def description(self) -> str:
        return (
            "Create or update an Ansible inventory file. Supports both INI and YAML formats. "
            "Can create new inventory, add hosts to groups, set host/group variables, "
            "or return the current inventory contents."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "read", "add_host", "add_group"],
                    "description": "Action to perform on the inventory",
                },
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "format": {
                    "type": "string",
                    "enum": ["yaml", "ini"],
                    "description": "Inventory format (default: yaml)",
                },
                "content": {
                    "type": "string",
                    "description": "Full inventory content to write (for 'create' action)",
                },
                "host": {
                    "type": "string",
                    "description": "Hostname or IP to add (for 'add_host')",
                },
                "group": {
                    "type": "string",
                    "description": "Group name (for 'add_host' / 'add_group')",
                },
                "variables": {
                    "type": "object",
                    "description": "Host or group variables to set",
                    "additionalProperties": {},
                },
                "environment": {
                    "type": "string",
                    "description": (
                        "Environment name (e.g. 'production', 'staging'). When provided, "
                        "creates inventory under inventory/<environment>/ with group_vars/ "
                        "and host_vars/ directories following Ansible best practices."
                    ),
                },
            },
            "required": ["action", "workspace_path"],
        }

    async def execute(
        self,
        action: str = "",
        workspace_path: str = "",
        format: str = "yaml",
        content: str = "",
        host: str = "",
        group: str = "all",
        variables: dict[str, Any] | None = None,
        environment: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not action or not workspace_path:
            return ToolResult.fail("action and workspace_path are required")

        if environment:
            inv_dir = Path(workspace_path) / "inventory" / environment
        else:
            inv_dir = Path(workspace_path) / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)

        if environment:
            (inv_dir / "group_vars").mkdir(exist_ok=True)
            (inv_dir / "host_vars").mkdir(exist_ok=True)

        ext = ".yml" if format == "yaml" else ".ini"
        inv_file = inv_dir / f"hosts{ext}"

        if action == "create":
            if not content:
                return ToolResult.fail("content is required for 'create' action")
            inv_file.write_text(content, encoding="utf-8")
            return ToolResult.ok(
                output=f"Inventory created at {inv_file}", path=str(inv_file)
            )

        if action == "read":
            if not inv_file.exists():
                return ToolResult.fail(f"Inventory file not found: {inv_file}")
            return ToolResult.ok(
                output=inv_file.read_text(encoding="utf-8"), path=str(inv_file)
            )

        if action == "add_host":
            if not host:
                return ToolResult.fail("host is required for 'add_host' action")
            inventory = self._load_yaml_inventory(inv_file)
            group_key = group or "all"
            if group_key not in inventory:
                inventory[group_key] = {"hosts": {}}
            if "hosts" not in inventory[group_key]:
                inventory[group_key]["hosts"] = {}
            inventory[group_key]["hosts"][host] = variables or {}
            self._save_yaml_inventory(inv_file, inventory)
            return ToolResult.ok(
                output=f"Host '{host}' added to group '{group_key}'",
                path=str(inv_file),
            )

        if action == "add_group":
            if not group:
                return ToolResult.fail("group is required for 'add_group' action")
            inventory = self._load_yaml_inventory(inv_file)
            if group not in inventory:
                inventory[group] = {"hosts": {}}
            if variables:
                inventory[group]["vars"] = variables
            self._save_yaml_inventory(inv_file, inventory)
            return ToolResult.ok(
                output=f"Group '{group}' added to inventory",
                path=str(inv_file),
            )

        return ToolResult.fail(f"Unknown action: {action}")

    @staticmethod
    def _load_yaml_inventory(path: Path) -> dict[str, Any]:
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        return {"all": {"hosts": {}}}

    @staticmethod
    def _save_yaml_inventory(path: Path, data: dict[str, Any]) -> None:
        path.write_text(
            yaml.dump(data, default_flow_style=False, sort_keys=False), encoding="utf-8"
        )
