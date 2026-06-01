"""Agent tool for discovering hosts via Ansible dynamic inventory plugins."""

from __future__ import annotations

import asyncio
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import yaml

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
            "Runs `ansible-inventory --list` with the given plugin config, persists "
            "discovered hosts into the infrastructure store, AND writes a YAML inventory "
            "file to workspace/inventory/ ready for execute_playbook and run_adhoc."
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
                "write_inventory": {
                    "type": "boolean",
                    "description": (
                        "Write a YAML inventory file to workspace/inventory/ from "
                        "discovered hosts (default: true). The file is immediately "
                        "usable by execute_playbook and run_adhoc."
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

        write_inventory = kwargs.get("write_inventory", True)
        inv_file_msg = ""
        if write_inventory and workspace_path and hostnames:
            inv_path = self._write_inventory_file(
                result["inventory"], source_id, Path(workspace_path),
            )
            if inv_path:
                inv_file_msg = f" Inventory file written: {inv_path.name}"

        if not hostnames:
            env_present = sorted(
                k for k in secret_env if k == k.upper()
            )[:10]
            diag_parts = [
                f"Discovered 0 hosts from {source_name}.",
                f"Plugin: {plugin_type}.",
                f"Env vars injected: {', '.join(env_present) or 'none'}.",
            ]
            raw_inv = result.get("inventory", {})
            raw_groups = [g for g in raw_inv if g not in ("_meta", "all", "ungrouped")]
            if raw_groups:
                diag_parts.append(f"Groups present (but empty): {', '.join(raw_groups[:10])}.")
            diag_parts.append(
                "Possible causes: instances not running, region/zone mismatch, "
                "missing tags/filters, insufficient IAM/RBAC permissions, "
                "or incorrect plugin configuration."
            )
            logger.warning(
                "discover_inventory_zero_hosts",
                source=source_name,
                plugin=plugin_type,
                env_vars=env_present,
            )
            return ToolResult.ok(
                output=" ".join(diag_parts),
                discovered=0,
                new=0,
                removed=removed,
                groups=groups,
                source_id=source_id,
            )

        return ToolResult.ok(
            output=(
                f"Discovered {len(hostnames)} host(s) from {source_name}. "
                f"{new_count} new, {removed} removed. "
                f"Groups: {', '.join(groups[:15]) or 'none'}.{inv_file_msg}"
            ),
            discovered=len(hostnames),
            new=new_count,
            removed=removed,
            groups=groups,
            source_id=source_id,
            inventory_file=str(inv_path) if write_inventory and inv_file_msg else None,
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

        proc = None
        try:
            proc = await asyncio.create_subprocess_exec(
                "ansible-inventory", "--list", "-i", str(config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=120)
        except asyncio.CancelledError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            config_path.unlink(missing_ok=True)
            raise
        except TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    pass
            config_path.unlink(missing_ok=True)
            return {"inventory": {}, "error": "ansible-inventory timed out after 120s"}
        finally:
            config_path.unlink(missing_ok=True)

        if proc.returncode != 0:
            stderr = stderr_b.decode(errors="replace").strip()
            return {"inventory": {}, "error": self._diagnose_error(stderr, plugin_type)}

        try:
            inventory = json.loads(stdout_b.decode(errors="replace"))
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
    def _write_inventory_file(
        inventory: dict[str, Any],
        source_id: str,
        workspace: Path,
    ) -> Path | None:
        """Generate a YAML inventory file from discovered inventory data."""
        hostvars = inventory.get("_meta", {}).get("hostvars", {})
        if not hostvars:
            return None

        groups: dict[str, dict[str, Any]] = {}
        for group_name, group_data in inventory.items():
            if group_name in ("_meta", "all", "ungrouped"):
                continue
            if not isinstance(group_data, dict):
                continue
            hosts = group_data.get("hosts", [])
            if not hosts:
                continue
            group_hosts: dict[str, dict[str, Any] | None] = {}
            for host in hosts:
                hvars = hostvars.get(host, {})
                host_entry: dict[str, Any] = {}
                for key in ("ansible_host", "ansible_user", "ansible_port",
                            "ansible_connection", "ansible_ssh_private_key_file"):
                    if key in hvars:
                        host_entry[key] = hvars[key]
                if not host_entry.get("ansible_host"):
                    ip = (hvars.get("private_ip_address", "")
                          or hvars.get("public_ip_address", ""))
                    if ip:
                        host_entry["ansible_host"] = ip
                group_hosts[host] = host_entry or None
            groups[group_name] = {"hosts": group_hosts}
            group_vars = group_data.get("vars")
            if group_vars:
                groups[group_name]["vars"] = group_vars

        if not groups:
            all_hosts: dict[str, dict[str, Any] | None] = {}
            for host, hvars in hostvars.items():
                entry: dict[str, Any] = {}
                for key in ("ansible_host", "ansible_user", "ansible_port",
                            "ansible_connection"):
                    if key in hvars:
                        entry[key] = hvars[key]
                if not entry.get("ansible_host"):
                    ip = (hvars.get("private_ip_address", "")
                          or hvars.get("public_ip_address", ""))
                    if ip:
                        entry["ansible_host"] = ip
                all_hosts[host] = entry or None
            groups = {"discovered": {"hosts": all_hosts}}

        inv_content = {"all": {"children": groups}}

        inv_dir = workspace / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        inv_path = inv_dir / f"{source_id}_hosts.yml"
        inv_path.write_text(yaml.dump(inv_content, default_flow_style=False, sort_keys=False))
        logger.info("inventory_file_written", path=str(inv_path), hosts=len(hostvars))
        return inv_path

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
