"""Agent tool for discovering hosts via Ansible dynamic inventory plugins."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from ansible_forge.inventory.templates import get_template
from ansible_forge.logging import get_logger
from ansible_forge.persistence.infrastructure_store import InfrastructureStore
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult, ToolStatus

logger = get_logger(__name__)

_PLUGIN_NOT_FOUND_RE = re.compile(
    r"(unable to locate|could not find|plugin not found|no inventory plugin)",
    re.IGNORECASE,
)
_AUTH_ERROR_RE = re.compile(
    r"(access denied|authentication|credentials|unauthorized|forbidden|ExpiredToken)",
    re.IGNORECASE,
)


class InventoryDiscoveryTool(BaseTool):
    @property
    def name(self) -> str:
        return "discover_inventory"

    @property
    def description(self) -> str:
        return (
            "Discover hosts from a cloud or dynamic inventory source using Ansible's "
            "native inventory plugins (aws_ec2, azure_rm, gcp_compute, etc.). "
            "Runs `ansible-inventory --list` with the given plugin config, parses the "
            "result, and persists discovered hosts into the infrastructure store."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plugin_type": {
                    "type": "string",
                    "description": (
                        "Ansible inventory plugin FQCN, e.g. 'amazon.aws.aws_ec2', "
                        "'azure.azcollection.azure_rm', 'google.cloud.gcp_compute'."
                    ),
                },
                "config_yaml": {
                    "type": "string",
                    "description": (
                        "Full YAML config for the inventory plugin. "
                        "If empty, uses the built-in template defaults for the plugin_type."
                    ),
                },
                "source_name": {
                    "type": "string",
                    "description": (
                        "Name for this inventory source (saved for future refreshes). "
                        "Defaults to the plugin_type."
                    ),
                },
            },
            "required": ["plugin_type"],
        }

    async def execute(self, **kwargs: Any) -> ToolResult:
        plugin_type: str = kwargs.get("plugin_type", "")
        config_yaml: str = kwargs.get("config_yaml", "")
        source_name: str = kwargs.get("source_name", "") or plugin_type
        workspace_path: str = kwargs.get("workspace_path", "")
        session_id: str = kwargs.get("_session_id", "")

        if not plugin_type:
            return ToolResult.fail("plugin_type is required")

        if not config_yaml:
            tmpl = get_template(plugin_type)
            if not tmpl or plugin_type == "generic":
                return ToolResult.fail(
                    f"No built-in template for '{plugin_type}'. "
                    "Provide config_yaml with the full plugin configuration."
                )
            config_yaml = tmpl["default_config"]

        missing = self._check_credentials(plugin_type, session_id)
        if missing:
            return ToolResult(
                status=ToolStatus.ERROR,
                output=(
                    f"Missing credentials for {plugin_type}. "
                    f"Please use the `request_secret` tool to ask the user for "
                    f"each of these: {', '.join(missing)}. "
                    f"Name each secret exactly as shown (e.g. name='AWS_ACCESS_KEY_ID') "
                    f"so they are injected as environment variables during discovery."
                ),
                error=f"Missing credentials: {', '.join(missing)}",
            )

        source_id = re.sub(r"[^a-zA-Z0-9_-]", "_", source_name.lower())

        store = InfrastructureStore.get_instance()
        store.upsert_source(
            source_id=source_id,
            name=source_name,
            plugin_type=plugin_type,
            config_yaml=config_yaml,
        )
        store.update_source_sync_status(source_id, "syncing")

        secret_env = self._build_secret_env(session_id)

        try:
            result = await self._run_discovery(
                plugin_type, config_yaml, workspace_path, secret_env,
            )
        except Exception as exc:
            store.update_source_sync_status(source_id, f"error: {exc}")
            return ToolResult.fail(f"Discovery failed: {exc}")

        if result.get("error"):
            store.update_source_sync_status(source_id, f"error: {result['error']}")
            return ToolResult.fail(result["error"])

        hostnames, new_count = self._persist_hosts(
            result["inventory"], source_id, store,
        )
        removed = store.purge_stale_hosts(source_id, hostnames)
        store.update_source_sync_status(
            source_id, "synced", host_count=len(hostnames),
        )

        groups = [
            g for g in result["inventory"]
            if g not in ("_meta", "all", "ungrouped")
        ]

        return ToolResult.ok(
            output=(
                f"Discovered {len(hostnames)} host(s) from {source_name}. "
                f"{new_count} new, {removed} removed. "
                f"Groups: {', '.join(groups[:15]) or 'none'}"
            ),
            discovered=len(hostnames),
            new=new_count,
            removed=removed,
            groups=groups,
            source_id=source_id,
        )

    def _check_credentials(self, plugin_type: str, session_id: str) -> list[str]:
        """Return list of required env vars that are neither in the environment nor the vault."""
        tmpl = get_template(plugin_type)
        if not tmpl:
            return []

        required = tmpl.get("required_env_vars", [])
        if not required:
            return []

        vault_keys: set[str] = set()
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            vault_keys = set(vault.get_all().keys())

        return [
            var for var in required
            if var not in os.environ and var not in vault_keys
        ]

    @staticmethod
    def _build_secret_env(session_id: str) -> dict[str, str]:
        """Pull all session secrets that look like env vars (UPPER_CASE names)."""
        if not session_id:
            return {}
        vault = SecretVault.get_instance().for_session(session_id)
        return {
            name: value
            for name, value in vault.get_all().items()
            if name == name.upper()
        }

    async def _run_discovery(
        self,
        plugin_type: str,
        config_yaml: str,
        workspace_path: str,
        secret_env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        suffix = plugin_type.split(".")[-1]
        tmp_dir = Path(workspace_path) / "inventory" if workspace_path else None

        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=f"_{suffix}.yml",
            dir=str(tmp_dir) if tmp_dir and tmp_dir.is_dir() else None,
            delete=False,
        ) as f:
            f.write(config_yaml)
            config_path = Path(f.name)

        env = os.environ.copy()
        if secret_env:
            env.update(secret_env)

        try:
            proc = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: subprocess.run(
                        ["ansible-inventory", "--list", "-i", str(config_path)],
                        capture_output=True,
                        text=True,
                        timeout=120,
                        env=env,
                    ),
                ),
                timeout=130,
            )
        finally:
            config_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            stderr = proc.stderr.strip()
            return {"inventory": {}, "error": self._diagnose_error(stderr, plugin_type)}

        try:
            inventory = json.loads(proc.stdout)
        except json.JSONDecodeError:
            return {"inventory": {}, "error": "ansible-inventory returned non-JSON output"}

        return {"inventory": inventory, "error": None}

    def _diagnose_error(self, stderr: str, plugin_type: str) -> str:
        if _PLUGIN_NOT_FOUND_RE.search(stderr):
            tmpl = get_template(plugin_type)
            collections = tmpl["required_collections"] if tmpl else [plugin_type.rsplit(".", 1)[0]]
            install_cmd = " ".join(f"ansible-galaxy collection install {c}" for c in collections)
            return (
                f"Inventory plugin '{plugin_type}' not found. "
                f"Install the required collection: {install_cmd}"
            )
        if _AUTH_ERROR_RE.search(stderr):
            tmpl = get_template(plugin_type)
            env_vars = tmpl["required_env_vars"] if tmpl else []
            hint = f" Required env vars: {', '.join(env_vars)}" if env_vars else ""
            return f"Authentication failed for '{plugin_type}'.{hint}"
        first_lines = "\n".join(stderr.splitlines()[:5])
        return f"ansible-inventory failed:\n{first_lines}"

    @staticmethod
    def _persist_hosts(
        inventory: dict[str, Any],
        source_id: str,
        store: InfrastructureStore,
    ) -> tuple[set[str], int]:
        hostvars = inventory.get("_meta", {}).get("hostvars", {})
        group_map: dict[str, list[str]] = {}
        for group_name, group_data in inventory.items():
            if group_name in ("_meta", "all"):
                continue
            if isinstance(group_data, dict):
                for host in group_data.get("hosts", []):
                    group_map.setdefault(host, []).append(group_name)

        existing_ids = {h["hostname"] for h in store.list_hosts(source_id=source_id)}
        hostnames: set[str] = set()
        new_count = 0

        for hostname, hvars in hostvars.items():
            hostnames.add(hostname)
            groups = group_map.get(hostname, [])
            ip_address = str(
                hvars.get("ansible_host", "")
                or hvars.get("private_ip_address", "")
                or hvars.get("public_ip_address", "")
            )
            ansible_user = str(hvars.get("ansible_user", ""))
            if hostname not in existing_ids:
                new_count += 1
            store.upsert_host(
                hostname=hostname,
                ip_address=ip_address,
                groups=groups,
                variables=hvars,
                ansible_user=ansible_user,
                source_id=source_id,
                status="discovered",
            )

        for hostname in group_map:
            if hostname not in hostvars:
                hostnames.add(hostname)
                if hostname not in existing_ids:
                    new_count += 1
                store.upsert_host(
                    hostname=hostname,
                    groups=group_map[hostname],
                    source_id=source_id,
                    status="discovered",
                )

        return hostnames, new_count
