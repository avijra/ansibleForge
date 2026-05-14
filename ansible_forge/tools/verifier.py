"""Post-deploy state verification — the infra equivalent of "run tests"."""

from __future__ import annotations

import asyncio
import functools
from pathlib import Path
from typing import Any

import ansible_runner

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult
from ansible_forge.tools.executor import isolated_runner_dir, materialize_ssh_keys

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")

VERIFY_PLAYBOOK_TEMPLATE = """\
---
- name: "Verify: {description}"
  hosts: "{hosts}"
  gather_facts: false
  become: {become}
  tasks:
{tasks_yaml}
"""


class Verifier(BaseTool):

    @property
    def name(self) -> str:
        return "verify_state"

    @property
    def description(self) -> str:
        return (
            "Verify infrastructure state after a deployment by running ad-hoc checks "
            "on target hosts. Checks can include: service status, port listening, "
            "HTTP endpoint reachability, file existence, command output matching. "
            "Returns structured pass/fail evidence for each check. "
            "Always use this after a successful playbook apply to confirm changes took effect."
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
                "inventory": {
                    "type": "string",
                    "description": "Inventory filename in workspace/inventory/",
                },
                "hosts": {
                    "type": "string",
                    "description": "Host or group pattern to target (default: 'all')",
                },
                "checks": {
                    "type": "array",
                    "description": "List of verification checks to run",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": [
                                    "service_running",
                                    "port_listening",
                                    "http_reachable",
                                    "file_exists",
                                    "command_output",
                                    "process_running",
                                ],
                                "description": "Type of verification check",
                            },
                            "target": {
                                "type": "string",
                                "description": "What to check (service name, port number, URL, file path, or command)",
                            },
                            "expected": {
                                "type": "string",
                                "description": "Expected value or substring (for command_output type)",
                            },
                        },
                        "required": ["type", "target"],
                    },
                },
            },
            "required": ["workspace_path", "inventory", "checks"],
        }

    @staticmethod
    def _materialize_ssh_keys(keys_dir: Path, merged_vars: dict[str, Any]) -> list[Path]:
        return materialize_ssh_keys(keys_dir, merged_vars)

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
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

    @staticmethod
    def _build_tasks(checks: list[dict[str, Any]]) -> str:
        tasks: list[str] = []
        for i, check in enumerate(checks):
            ctype = check.get("type", "")
            target = check.get("target", "")
            expected = check.get("expected", "")

            if ctype == "service_running":
                tasks.append(
                    f'    - name: "Check service: {target}"\n'
                    f"      ansible.builtin.service_facts:\n"
                    f"      register: svc_facts_{i}\n\n"
                    f'    - name: "Assert {target} is running"\n'
                    f"      ansible.builtin.assert:\n"
                    f"        that:\n"
                    f'          - "svc_facts_{i}.ansible_facts.services[\'{target}.service\'].state == \'running\'"\n'
                    f"        fail_msg: \"Service {target} is NOT running\"\n"
                    f"        success_msg: \"Service {target} is running\"\n"
                )
            elif ctype == "port_listening":
                tasks.append(
                    f'    - name: "Check port {target} is listening"\n'
                    f"      ansible.builtin.wait_for:\n"
                    f"        port: {target}\n"
                    f"        timeout: 5\n"
                    f"        state: started\n"
                    f"      register: port_check_{i}\n"
                )
            elif ctype == "http_reachable":
                tasks.append(
                    f'    - name: "Check HTTP endpoint: {target}"\n'
                    f"      ansible.builtin.uri:\n"
                    f'        url: "{target}"\n'
                    f"        method: GET\n"
                    f"        status_code: [200, 301, 302]\n"
                    f"        timeout: 10\n"
                    f"        validate_certs: false\n"
                    f"      register: http_check_{i}\n"
                )
            elif ctype == "file_exists":
                tasks.append(
                    f'    - name: "Check file exists: {target}"\n'
                    f"      ansible.builtin.stat:\n"
                    f'        path: "{target}"\n'
                    f"      register: file_check_{i}\n\n"
                    f'    - name: "Assert file exists: {target}"\n'
                    f"      ansible.builtin.assert:\n"
                    f"        that: file_check_{i}.stat.exists\n"
                    f"        fail_msg: \"File {target} does NOT exist\"\n"
                    f"        success_msg: \"File {target} exists\"\n"
                )
            elif ctype == "command_output":
                tasks.append(
                    f'    - name: "Run command: {target}"\n'
                    f"      ansible.builtin.command: {target}\n"
                    f"      register: cmd_check_{i}\n"
                    f"      changed_when: false\n"
                    f"      failed_when: false\n\n"
                    f'    - name: "Assert command output contains: {expected}"\n'
                    f"      ansible.builtin.assert:\n"
                    f"        that:\n"
                    f'          - "\'{expected}\' in cmd_check_{i}.stdout"\n'
                    f"        fail_msg: \"Command output did not contain '{expected}'\"\n"
                    f"        success_msg: \"Command output matches expected\"\n"
                )
            elif ctype == "process_running":
                tasks.append(
                    f'    - name: "Check process: {target}"\n'
                    f"      ansible.builtin.command: pgrep -f {target}\n"
                    f"      register: proc_check_{i}\n"
                    f"      changed_when: false\n"
                    f"      failed_when: false\n\n"
                    f'    - name: "Assert process {target} is running"\n'
                    f"      ansible.builtin.assert:\n"
                    f"        that: proc_check_{i}.rc == 0\n"
                    f"        fail_msg: \"Process {target} is NOT running\"\n"
                    f"        success_msg: \"Process {target} is running\"\n"
                )

        return "\n".join(tasks)

    async def execute(
        self,
        workspace_path: str = "",
        inventory: str = "",
        hosts: str = "all",
        checks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not inventory or not checks:
            return ToolResult.fail("workspace_path, inventory, and checks are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        tasks_yaml = self._build_tasks(checks)
        if not tasks_yaml.strip():
            return ToolResult.fail("No valid checks provided")

        description = ", ".join(c.get("target", "") for c in checks[:3])
        needs_become = any(
            c.get("type") in ("service_running", "port_listening", "process_running")
            for c in checks
        )
        playbook_content = VERIFY_PLAYBOOK_TEMPLATE.format(
            description=description,
            hosts=hosts,
            become="true" if needs_become else "false",
            tasks_yaml=tasks_yaml,
        )

        import uuid as _uuid

        ws.mkdir(parents=True, exist_ok=True)
        pb_name = f"_verify_{_uuid.uuid4().hex[:8]}.yml"
        verify_pb = ws / pb_name
        verify_pb.write_text(playbook_content, encoding="utf-8")

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())

        with isolated_runner_dir(ws) as run_dir:
            self._materialize_ssh_keys(run_dir / "ssh_keys", extravars)

            runner_kwargs: dict[str, Any] = {
                "private_data_dir": str(run_dir),
                "project_dir": str(ws),
                "playbook": pb_name,
                "inventory": str(inv_path),
            }
            if extravars:
                runner_kwargs["extravars"] = extravars

            loop = asyncio.get_event_loop()
            try:
                result = await asyncio.wait_for(
                    loop.run_in_executor(
                        None, functools.partial(ansible_runner.run, **runner_kwargs)
                    ),
                    timeout=120,
                )
            except TimeoutError:
                return ToolResult.fail("Verification timed out after 2 minutes.")

            results: list[dict[str, Any]] = []
            for event in result.events:
                etype = event.get("event", "")
                edata = event.get("event_data", {})
                task_name = edata.get("task", "")
                host = edata.get("host", "")
                res = edata.get("res", {})

                if etype == "runner_on_ok" and "assert" in task_name.lower():
                    results.append({
                        "check": task_name,
                        "host": host,
                        "status": "PASS",
                        "message": res.get("msg", "OK"),
                    })
                elif etype == "runner_on_failed":
                    results.append({
                        "check": task_name,
                        "host": host,
                        "status": "FAIL",
                        "message": res.get("msg", res.get("assertion", "Failed")),
                    })
                elif etype == "runner_on_ok" and task_name.startswith("Check "):
                    results.append({
                        "check": task_name,
                        "host": host,
                        "status": "PASS",
                        "message": "OK",
                    })

        passed = sum(1 for r in results if r["status"] == "PASS")
        failed = sum(1 for r in results if r["status"] == "FAIL")
        total = passed + failed

        verify_pb.unlink(missing_ok=True)

        if failed > 0:
            return ToolResult.fail(
                f"Verification: {failed}/{total} checks FAILED. "
                f"{passed}/{total} passed.",
                results=results,
                passed=passed,
                failed=failed,
            )

        return ToolResult.ok(
            output=f"Verification: {passed}/{total} checks PASSED.",
            results=results,
            passed=passed,
            failed=failed,
        )
