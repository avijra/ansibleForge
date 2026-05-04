"""Inspect Ansible variable precedence for hosts — show where each variable comes from."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

PRECEDENCE_LEVELS = [
    ("role_defaults", 1),
    ("inventory_group_all", 2),
    ("inventory_group", 3),
    ("inventory_host", 4),
    ("host_vars_file", 5),
    ("group_vars_file", 6),
    ("role_vars", 7),
    ("play_vars", 8),
    ("extra_vars", 9),
    ("cached_facts", 10),
]


class VariableInspector(BaseTool):
    @property
    def name(self) -> str:
        return "inspect_variables"

    @property
    def description(self) -> str:
        return (
            "Show the full variable resolution chain for a host: where each variable "
            "comes from (inventory, group_vars, host_vars, role defaults, facts) and "
            "which value wins based on Ansible's precedence rules. Essential for debugging "
            "'why is this variable wrong?' issues."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "workspace_path": {
                    "type": "string",
                    "description": "Absolute path to the workspace directory",
                },
                "hostname": {
                    "type": "string",
                    "description": "Hostname to inspect variables for",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "variable_name": {
                    "type": "string",
                    "description": "Specific variable to trace (optional — shows all if omitted)",
                },
            },
            "required": ["workspace_path", "hostname", "inventory"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        hostname: str = "",
        inventory: str = "",
        variable_name: str = "",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not hostname or not inventory:
            return ToolResult.fail("workspace_path, hostname, and inventory are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        var_chain: dict[str, list[dict[str, Any]]] = {}

        self._scan_inventory(inv_path, hostname, var_chain)

        project_dir = ws
        if project_dir.exists():
            self._scan_group_vars(project_dir, hostname, var_chain)
            self._scan_host_vars(project_dir, hostname, var_chain)
            self._scan_role_defaults(project_dir, var_chain)
            self._scan_role_vars(project_dir, var_chain)

        self._scan_cached_facts(ws, hostname, var_chain)

        resolved: dict[str, dict[str, Any]] = {}
        for var_name, sources in var_chain.items():
            if variable_name and var_name != variable_name:
                continue
            sources_sorted = sorted(sources, key=lambda s: s.get("precedence", 0))
            winner = sources_sorted[-1] if sources_sorted else {}
            resolved[var_name] = {
                "effective_value": winner.get("value"),
                "source": winner.get("source", "unknown"),
                "precedence": winner.get("precedence", 0),
                "all_sources": sources_sorted,
                "overridden": len(sources_sorted) > 1,
            }

        if variable_name and variable_name not in resolved:
            return ToolResult.fail(
                f"Variable '{variable_name}' not found for host '{hostname}'. "
                f"Available variables: {', '.join(sorted(var_chain.keys())[:30])}"
            )

        overridden = sum(1 for v in resolved.values() if v["overridden"])

        return ToolResult.ok(
            output=(
                f"Inspected {len(resolved)} variable(s) for host '{hostname}'. "
                f"{overridden} variable(s) have multiple sources (precedence conflict)."
            ),
            variables=resolved,
            hostname=hostname,
            total_variables=len(resolved),
            overridden_count=overridden,
        )

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        stripped = inventory.removeprefix("inventory/").removeprefix("inventory\\")
        candidates = [ws / "inventory" / stripped, ws / inventory, ws / "inventory" / inventory]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _add_var(
        self,
        chain: dict[str, list[dict[str, Any]]],
        name: str,
        value: Any,
        source: str,
        precedence: int,
    ) -> None:
        chain.setdefault(name, []).append({
            "value": value,
            "source": source,
            "precedence": precedence,
        })

    def _scan_inventory(
        self, inv_path: Path, hostname: str, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        try:
            content = inv_path.read_text(encoding="utf-8")
        except Exception:
            return

        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            self._scan_ini_inventory(content, hostname, chain)
            return

        if not isinstance(data, dict):
            return

        all_group = data.get("all", {})
        if isinstance(all_group, dict):
            all_vars = all_group.get("vars", {})
            if isinstance(all_vars, dict):
                for k, v in all_vars.items():
                    self._add_var(chain, k, v, f"inventory:all:vars ({inv_path.name})", 2)

            self._scan_yaml_groups(all_group.get("children", {}), hostname, chain, inv_path.name)

    def _scan_yaml_groups(
        self, children: Any, hostname: str, chain: dict[str, list[dict[str, Any]]], fname: str
    ) -> None:
        if not isinstance(children, dict):
            return
        for group_name, group_data in children.items():
            if not isinstance(group_data, dict):
                continue
            hosts = group_data.get("hosts", {})
            if isinstance(hosts, dict):
                group_vars = group_data.get("vars", {})
                if isinstance(group_vars, dict):
                    for host_key in hosts:
                        if hostname in (host_key, hosts.get(host_key, {}).get("ansible_host", "")):
                            for k, v in group_vars.items():
                                self._add_var(chain, k, v, f"inventory:{group_name}:vars ({fname})", 3)

                for host_key, host_data in hosts.items():
                    if hostname not in (host_key, (host_data or {}).get("ansible_host", "")):
                        continue
                    if isinstance(host_data, dict):
                        for k, v in host_data.items():
                            self._add_var(chain, k, v, f"inventory:{group_name}:host:{host_key} ({fname})", 4)

            sub_children = group_data.get("children", {})
            if isinstance(sub_children, dict):
                self._scan_yaml_groups(sub_children, hostname, chain, fname)

    def _scan_ini_inventory(
        self, content: str, hostname: str, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        current_group = "ungrouped"
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith(";"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current_group = line[1:-1].split(":")[0]
                continue
            parts = line.split()
            host_name = parts[0]
            if hostname not in host_name:
                continue
            for part in parts[1:]:
                if "=" in part:
                    k, v = part.split("=", 1)
                    self._add_var(chain, k, v, f"inventory:{current_group}:host (INI)", 4)

    def _scan_group_vars(
        self, project_dir: Path, hostname: str, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        group_vars_dir = project_dir / "group_vars"
        if not group_vars_dir.exists():
            return
        for path in group_vars_dir.iterdir():
            if path.is_file() and path.suffix in (".yml", ".yaml"):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, v in data.items():
                            self._add_var(chain, k, v, f"group_vars/{path.name}", 6)
                except yaml.YAMLError:
                    continue
            elif path.is_dir():
                for sub in path.iterdir():
                    if sub.suffix in (".yml", ".yaml"):
                        try:
                            data = yaml.safe_load(sub.read_text(encoding="utf-8"))
                            if isinstance(data, dict):
                                for k, v in data.items():
                                    self._add_var(chain, k, v, f"group_vars/{path.name}/{sub.name}", 6)
                        except yaml.YAMLError:
                            continue

    def _scan_host_vars(
        self, project_dir: Path, hostname: str, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        host_vars_dir = project_dir / "host_vars"
        if not host_vars_dir.exists():
            return

        for path in host_vars_dir.iterdir():
            name_match = hostname in path.stem
            if not name_match:
                continue
            if path.is_file() and path.suffix in (".yml", ".yaml"):
                try:
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, v in data.items():
                            self._add_var(chain, k, v, f"host_vars/{path.name}", 5)
                except yaml.YAMLError:
                    continue
            elif path.is_dir():
                for sub in path.iterdir():
                    if sub.suffix in (".yml", ".yaml"):
                        try:
                            data = yaml.safe_load(sub.read_text(encoding="utf-8"))
                            if isinstance(data, dict):
                                for k, v in data.items():
                                    self._add_var(chain, k, v, f"host_vars/{path.name}/{sub.name}", 5)
                        except yaml.YAMLError:
                            continue

    def _scan_role_defaults(
        self, project_dir: Path, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        roles_dir = project_dir / "roles"
        if not roles_dir.exists():
            return
        for role_dir in roles_dir.iterdir():
            if not role_dir.is_dir():
                continue
            defaults = role_dir / "defaults" / "main.yml"
            if defaults.exists():
                try:
                    data = yaml.safe_load(defaults.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, v in data.items():
                            self._add_var(chain, k, v, f"roles/{role_dir.name}/defaults/main.yml", 1)
                except yaml.YAMLError:
                    continue

    def _scan_role_vars(
        self, project_dir: Path, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        roles_dir = project_dir / "roles"
        if not roles_dir.exists():
            return
        for role_dir in roles_dir.iterdir():
            if not role_dir.is_dir():
                continue
            role_vars = role_dir / "vars" / "main.yml"
            if role_vars.exists():
                try:
                    data = yaml.safe_load(role_vars.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        for k, v in data.items():
                            self._add_var(chain, k, v, f"roles/{role_dir.name}/vars/main.yml", 7)
                except yaml.YAMLError:
                    continue

    def _scan_cached_facts(
        self, ws: Path, hostname: str, chain: dict[str, list[dict[str, Any]]]
    ) -> None:
        facts_file = ws / ".tuyere" / "artifacts" / "host_facts.json"
        if not facts_file.exists():
            return
        try:
            all_facts = json.loads(facts_file.read_text(encoding="utf-8"))
            host_facts = all_facts.get(hostname, {})
            for k, v in host_facts.items():
                fact_name = f"ansible_{k}" if not k.startswith("ansible_") else k
                self._add_var(chain, fact_name, v, "cached facts (host_facts.json)", 10)
        except (json.JSONDecodeError, OSError):
            logger.debug("host_facts_parse_failed", exc_info=True)
