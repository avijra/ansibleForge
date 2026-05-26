"""Convert Terraform state/outputs into Ansible inventory for seamless handoff."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import yaml

from ansible_forge.logging import get_logger
from ansible_forge.persistence.infrastructure_store import InfrastructureStore
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.binary_resolver import resolve_terraform_or_download_async

logger = get_logger(__name__)


class TerraformInventoryBridge(BaseTool):
    @property
    def name(self) -> str:
        return "terraform_to_inventory"

    @property
    def description(self) -> str:
        return (
            "Read Terraform state and automatically generate an Ansible inventory from "
            "provisioned resources. Extracts IP addresses, hostnames, and metadata from "
            "Terraform-managed instances (EC2, Azure VMs, GCP instances, Droplets, etc.) "
            "and writes a YAML inventory file. Also registers hosts in the infrastructure "
            "store. This is the bridge between 'Terraform creates' and 'Ansible configures'."
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
                "inventory_name": {
                    "type": "string",
                    "description": "Name for the generated inventory file (default: 'terraform_hosts.yml')",
                },
                "group_name": {
                    "type": "string",
                    "description": "Ansible group name for the hosts (default: 'terraform')",
                },
                "ssh_user": {
                    "type": "string",
                    "description": "SSH user for connecting to hosts (e.g. 'ubuntu', 'ec2-user')",
                },
                "use_private_ip": {
                    "type": "boolean",
                    "description": "Use private IPs instead of public IPs (default: false)",
                },
                "extra_vars": {
                    "type": "object",
                    "description": "Additional host variables to add to inventory",
                    "additionalProperties": {},
                },
            },
            "required": ["workspace_path"],
        }

    async def execute(
        self,
        workspace_path: str = "",
        inventory_name: str = "terraform_hosts.yml",
        group_name: str = "terraform",
        ssh_user: str = "",
        use_private_ip: bool = False,
        extra_vars: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path:
            return ToolResult.fail("workspace_path is required")

        tf_dir = Path(workspace_path) / "terraform"
        if not tf_dir.exists():
            return ToolResult.fail("No terraform/ directory found in workspace")

        try:
            tf_binary = await resolve_terraform_or_download_async()
        except Exception as exc:
            return ToolResult.fail(f"Terraform/OpenTofu not available: {exc}")

        session_id = kwargs.get("_session_id", "")
        env = os.environ.copy()
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            for name, value in vault.get_all().items():
                if name.isupper() or name.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                    env[name] = str(value)
        env["TF_IN_AUTOMATION"] = "1"

        show_proc = await asyncio.create_subprocess_exec(
            tf_binary, "show", "-no-color", "-json",
            cwd=str(tf_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            show_stdout, show_stderr = await asyncio.wait_for(show_proc.communicate(), timeout=60)
        except asyncio.CancelledError:
            try:
                show_proc.kill()
                await show_proc.wait()
            except Exception:
                pass
            raise
        except TimeoutError:
            try:
                show_proc.kill()
                await show_proc.wait()
            except Exception:
                pass
            return ToolResult.fail("Terraform state read timed out")

        if show_proc.returncode != 0:
            return ToolResult.fail(f"Failed to read Terraform state: {show_stderr.decode(errors='replace').strip()}")

        try:
            state = json.loads(show_stdout.decode(errors="replace"))
        except json.JSONDecodeError:
            return ToolResult.fail("Failed to parse Terraform state JSON")

        resources = state.get("values", {}).get("root_module", {}).get("resources", [])
        hosts = self._extract_hosts(resources, use_private_ip)

        if not hosts:
            out_proc = await asyncio.create_subprocess_exec(
                tf_binary, "output", "-no-color", "-json",
                cwd=str(tf_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            try:
                out_stdout, _ = await asyncio.wait_for(out_proc.communicate(), timeout=30)
            except asyncio.CancelledError:
                try:
                    out_proc.kill()
                    await out_proc.wait()
                except Exception:
                    pass
                raise
            except TimeoutError:
                try:
                    out_proc.kill()
                    await out_proc.wait()
                except Exception:
                    pass
                out_stdout = b""
            if out_proc.returncode == 0 and out_stdout:
                try:
                    outputs = json.loads(out_stdout.decode(errors="replace"))
                    hosts = self._extract_hosts_from_outputs(outputs)
                except json.JSONDecodeError:
                    logger.debug("tf_outputs_parse_failed", exc_info=True)

        if not hosts:
            return ToolResult.fail(
                "No compute instances found in Terraform state. "
                "Ensure your Terraform config creates instances with public/private IPs."
            )

        inventory = self._build_inventory(hosts, group_name, ssh_user, extra_vars)

        inv_dir = Path(workspace_path) / "inventory"
        inv_dir.mkdir(parents=True, exist_ok=True)
        inv_file = inv_dir / inventory_name
        inv_file.write_text(yaml.dump(inventory, default_flow_style=False), encoding="utf-8")

        store = InfrastructureStore.get_instance()
        for host_info in hosts:
            store.upsert_host(
                host_id=host_info["name"],
                hostname=host_info["name"],
                ip_address=host_info.get("ip", ""),
                groups=[group_name],
                variables={
                    "ansible_host": host_info.get("ip", ""),
                    "terraform_resource": host_info.get("resource_type", ""),
                    "terraform_id": host_info.get("id", ""),
                    **({"ansible_user": ssh_user} if ssh_user else {}),
                },
                source_id="terraform",
            )

        return ToolResult.ok(
            output=(
                f"Generated Ansible inventory from Terraform: {len(hosts)} host(s) "
                f"in group '{group_name}' → {inv_file.name}"
            ),
            inventory_file=str(inv_file),
            hosts=[{
                "name": h["name"],
                "ip": h.get("ip", ""),
                "type": h.get("resource_type", ""),
            } for h in hosts],
            group=group_name,
        )

    def _extract_hosts(self, resources: list[dict], use_private_ip: bool) -> list[dict[str, str]]:
        hosts: list[dict[str, str]] = []

        compute_types = {
            "aws_instance": ("public_ip", "private_ip", "public_dns", "tags"),
            "azurerm_linux_virtual_machine": ("public_ip_address", "private_ip_address", "name", "tags"),
            "azurerm_virtual_machine": ("public_ip_address", "private_ip_address", "name", "tags"),
            "google_compute_instance": ("network_interface", None, "name", "labels"),
            "digitalocean_droplet": ("ipv4_address", "ipv4_address_private", "name", "tags"),
            "hcloud_server": ("ipv4_address", None, "name", "labels"),
            "linode_instance": ("ip_address", "private_ip_address", "label", "tags"),
        }

        for res in resources:
            rtype = res.get("type", "")
            if rtype not in compute_types:
                continue

            values = res.get("values", {}) or {}
            pub_key, priv_key, name_key, tags_key = compute_types[rtype]

            public_ip = ""
            private_ip = ""

            if rtype == "google_compute_instance":
                nics = values.get("network_interface", [])
                if nics and isinstance(nics, list):
                    private_ip = nics[0].get("network_ip", "")
                    access = nics[0].get("access_config", [])
                    if access and isinstance(access, list):
                        public_ip = access[0].get("nat_ip", "")
            else:
                public_ip = values.get(pub_key, "") or ""
                private_ip = values.get(priv_key, "") or "" if priv_key else ""

            ip = private_ip if use_private_ip else (public_ip or private_ip)
            if not ip:
                continue

            tags = values.get(tags_key, {}) or {}
            name = (
                (tags.get("Name", "") if isinstance(tags, dict) else "")
                or values.get(name_key, "")
                or values.get("name", "")
                or res.get("name", "")
            )

            hosts.append({
                "name": name or f"{rtype}-{len(hosts)}",
                "ip": ip,
                "public_ip": public_ip,
                "private_ip": private_ip,
                "resource_type": rtype,
                "id": values.get("id", ""),
                "instance_type": values.get("instance_type", values.get("size", values.get("machine_type", ""))),
            })

        return hosts

    def _extract_hosts_from_outputs(self, outputs: dict[str, Any]) -> list[dict[str, str]]:
        hosts: list[dict[str, str]] = []

        ip_keys = ("ip", "ips", "public_ip", "public_ips", "instance_ip", "host_ip", "server_ip")
        name_keys = ("name", "names", "hostname", "hostnames", "instance_name")

        ips: list[str] = []
        names: list[str] = []

        for key, val in outputs.items():
            value = val.get("value") if isinstance(val, dict) else val
            key_lower = key.lower()

            for ik in ip_keys:
                if ik in key_lower:
                    if isinstance(value, list):
                        ips.extend(str(v) for v in value if v)
                    elif isinstance(value, str) and value:
                        ips.append(value)

            for nk in name_keys:
                if nk in key_lower:
                    if isinstance(value, list):
                        names.extend(str(v) for v in value if v)
                    elif isinstance(value, str) and value:
                        names.append(value)

        for i, ip in enumerate(ips):
            hosts.append({
                "name": names[i] if i < len(names) else f"host-{i}",
                "ip": ip,
                "resource_type": "output",
                "id": "",
            })

        return hosts

    def _build_inventory(
        self,
        hosts: list[dict[str, str]],
        group_name: str,
        ssh_user: str,
        extra_vars: dict[str, Any] | None,
    ) -> dict[str, Any]:
        host_entries: dict[str, dict[str, Any]] = {}
        for h in hosts:
            entry: dict[str, Any] = {"ansible_host": h["ip"]}
            if ssh_user:
                entry["ansible_user"] = ssh_user
            entry["ansible_ssh_common_args"] = "-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
            if extra_vars:
                entry.update(extra_vars)
            host_entries[h["name"]] = entry

        return {
            "all": {
                "children": {
                    group_name: {
                        "hosts": host_entries,
                    },
                },
            },
        }
