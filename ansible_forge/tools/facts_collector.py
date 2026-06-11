"""Gather and query host facts via the Ansible setup module."""

from __future__ import annotations

import asyncio
import functools
import json
import os
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools._runner_diagnostics import (
    diagnose_runner_failure,
    read_runner_stdout,
)
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.ee_runtime import runner_locale_env
from ansible_forge.tools.executor import (
    _resolve_python_interpreter,
    get_runner_events,
    isolated_runner_dir,
    kill_stale_runner_procs,
    materialize_ssh_keys,
)

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")


def _facts_envvars() -> dict[str, str]:
    import sys

    envvars: dict[str, str] = {
        "ANSIBLE_PYTHON_INTERPRETER": _resolve_python_interpreter(),
        "ANSIBLE_STDOUT_CALLBACK": "json",
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        **runner_locale_env(),
    }
    if getattr(sys, "frozen", False):
        envvars["PYTHONHOME"] = ""
        envvars["PYTHONPATH"] = ""
    return envvars


class FactsCollector(BaseTool):
    @property
    def name(self) -> str:
        return "collect_facts"

    @property
    def description(self) -> str:
        return (
            "Gather host facts by running the Ansible setup module against target hosts. "
            "Returns structured facts (OS, network, hardware, packages, etc.) "
            "that can be used for conditional playbook generation."
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
                "host_pattern": {
                    "type": "string",
                    "description": "Host or group pattern to target (default: 'all')",
                },
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "gather_subset": {
                    "type": "string",
                    "description": "Comma-separated fact subsets (e.g. 'network,hardware'). Default: 'all'",
                },
            },
            "required": ["workspace_path", "inventory"],
        }

    @staticmethod
    def _materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
        """Write SSH key secrets into keys_dir (inside isolated run_dir)."""
        return materialize_ssh_keys(keys_dir, merged_vars)

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        """Resolve inventory path, handling cases where the agent includes 'inventory/' prefix."""
        # Strip leading 'inventory/' if the agent already included it
        stripped = inventory.removeprefix("inventory/").removeprefix("inventory\\")
        candidates = [
            ws / "inventory" / stripped,
            ws / inventory,
            ws / "inventory" / inventory,
        ]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    async def execute(
        self,
        workspace_path: str = "",
        host_pattern: str = "all",
        inventory: str = "",
        gather_subset: str = "all",
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not inventory:
            return ToolResult.fail("workspace_path and inventory are required")

        from ansible_forge.tools.python_resolver import resolve_or_install_python_async

        await resolve_or_install_python_async()

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(
                f"Inventory not found: {inv_path}. "
                f"Tried: {ws / 'inventory' / inventory}, {ws / inventory}"
            )

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())
        (ws / ".tuyere").mkdir(parents=True, exist_ok=True)

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", extravars)

            envvars = _facts_envvars()
            for key, value in extravars.items():
                if key.isupper() or key.startswith(("AWS_", "ARM_", "GOOGLE_", "TF_", "DIGITALOCEAN_", "HCLOUD_", "DO_")):
                    envvars[key] = str(value)
            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "project_dir": str(ws),
                "module": "ansible.builtin.setup",
                "module_args": f"gather_subset={gather_subset}",
                "host_pattern": host_pattern,
                "inventory": str(inv_path),
                "envvars": envvars,
            }
            if extravars:
                runner_kwargs["extravars"] = extravars

            from ansible_forge.tools.ee_runtime import configure_ee_runner

            await configure_ee_runner(
                ws, run_dir, runner_kwargs, inventory_path=inv_path
            )

            loop = asyncio.get_running_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, functools.partial(ansible_runner.run, **runner_kwargs)
                    ),
                    timeout=120,
                )
            except TimeoutError:
                kill_stale_runner_procs(run_dir)
                return ToolResult.fail(
                    "Could not gather system information within 2 minutes. "
                    "Check that hosts are reachable and credentials are correct."
                )

            host_facts: dict[str, Any] = {}
            for event in get_runner_events(result):
                if event.get("event") in ("runner_on_ok", "runner_on_changed"):
                    host = event.get("event_data", {}).get("host", "unknown")
                    facts = event.get("event_data", {}).get("res", {}).get("ansible_facts", {})
                    host_facts[host] = {
                        "os_family": facts.get("ansible_os_family", ""),
                        "distribution": facts.get("ansible_distribution", ""),
                        "distribution_version": facts.get("ansible_distribution_version", ""),
                        "hostname": facts.get("ansible_hostname", ""),
                        "fqdn": facts.get("ansible_fqdn", ""),
                        "kernel": facts.get("ansible_kernel", ""),
                        "architecture": facts.get("ansible_architecture", ""),
                        "python_version": facts.get("ansible_python_version", ""),
                        "interfaces": facts.get("ansible_interfaces", []),
                        "memory_mb": facts.get("ansible_memtotal_mb", 0),
                        "processor_count": facts.get("ansible_processor_count", 0),
                        "pkg_mgr": facts.get("ansible_pkg_mgr", ""),
                        "service_mgr": facts.get("ansible_service_mgr", ""),
                        "python_interpreter": facts.get("ansible_python", {}).get("executable", ""),
                        "selinux": facts.get("ansible_selinux", {}).get("status", ""),
                        "apparmor": facts.get("ansible_apparmor", {}).get("status", ""),
                        "default_ipv4": facts.get("ansible_default_ipv4", {}).get("address", ""),
                        "virtualization_type": facts.get("ansible_virtualization_type", ""),
                        "mounts": [
                            {
                                "mount": m.get("mount", ""),
                                "size_total": m.get("size_total", 0),
                                "size_available": m.get("size_available", 0),
                                "fstype": m.get("fstype", ""),
                            }
                            for m in (facts.get("ansible_mounts") or [])
                            if m.get("mount", "") in ("/", "/var", "/tmp", "/home")
                        ],
                    }

        if not host_facts:
            raw_stdout = read_runner_stdout(result)
            diag = diagnose_runner_failure(
                get_runner_events(result),
                raw_stdout=raw_stdout,
                rc=getattr(result, "rc", None),
            )
            return ToolResult.fail(
                f"Could not gather system information. {diag}",
                raw_stdout=raw_stdout[-4000:],
            )

        import tempfile

        facts_cache = Path(workspace_path) / ".tuyere" / "artifacts" / "host_facts.json"
        facts_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp_fd, tmp_path = tempfile.mkstemp(
            dir=str(facts_cache.parent), suffix=".tmp"
        )
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(host_facts, f, indent=2)
            os.replace(tmp_path, str(facts_cache))
        except BaseException:
            with __import__("contextlib").suppress(OSError):
                os.unlink(tmp_path)
            raise
        logger.info("facts_cached", path=str(facts_cache), hosts=len(host_facts))

        return ToolResult.ok(
            output=f"Gathered system information from {len(host_facts)} host(s) (OS, memory, network, etc.).",
            host_facts=host_facts,
        )
