"""Security and compliance scanning against hosts using built-in check templates."""

from __future__ import annotations

import asyncio
import functools
import os
import stat
import textwrap
from pathlib import Path
from typing import Any

import ansible_runner
import yaml

from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_SSH_KEY_HEADERS = ("-----BEGIN", "PRIVATE KEY")
_SSH_KEY_SECRET_NAMES = ("ssh_private_key", "ssh_key", "ansible_ssh_key", "private_key")

BUILTIN_CHECKS: dict[str, dict[str, Any]] = {
    "ssh_hardening": {
        "name": "SSH Hardening",
        "description": "Verify SSH daemon configuration follows security best practices",
        "tasks": [
            {
                "id": "ssh_root_login",
                "name": "Root login disabled",
                "command": "grep -E '^PermitRootLogin' /etc/ssh/sshd_config",
                "expect_contains": "no",
                "severity": "high",
                "remediation": "Set PermitRootLogin no in /etc/ssh/sshd_config",
            },
            {
                "id": "ssh_password_auth",
                "name": "Password authentication disabled",
                "command": "grep -E '^PasswordAuthentication' /etc/ssh/sshd_config",
                "expect_contains": "no",
                "severity": "medium",
                "remediation": "Set PasswordAuthentication no in /etc/ssh/sshd_config",
            },
            {
                "id": "ssh_protocol",
                "name": "SSH protocol version 2",
                "command": "ssh -V 2>&1 | head -1",
                "expect_contains": "OpenSSH",
                "severity": "high",
                "remediation": "Upgrade to OpenSSH with Protocol 2 support",
            },
            {
                "id": "ssh_empty_passwords",
                "name": "Empty passwords rejected",
                "command": "grep -E '^PermitEmptyPasswords' /etc/ssh/sshd_config || echo 'PermitEmptyPasswords no'",
                "expect_contains": "no",
                "severity": "high",
                "remediation": "Set PermitEmptyPasswords no in /etc/ssh/sshd_config",
            },
        ],
    },
    "firewall": {
        "name": "Firewall Configuration",
        "description": "Verify firewall is active and configured",
        "tasks": [
            {
                "id": "firewall_active",
                "name": "Firewall service running",
                "command": "systemctl is-active firewalld iptables ufw 2>/dev/null | grep -c active || echo 0",
                "expect_not": "0",
                "severity": "high",
                "remediation": "Enable and start a firewall service (firewalld, iptables, or ufw)",
            },
        ],
    },
    "user_security": {
        "name": "User Account Security",
        "description": "Check user account and password policies",
        "tasks": [
            {
                "id": "no_empty_passwords",
                "name": "No users with empty passwords",
                "command": "awk -F: '($2 == \"\" || $2 == \"!\") {print $1}' /etc/shadow 2>/dev/null | wc -l",
                "expect_contains": "0",
                "severity": "critical",
                "remediation": "Set passwords for all user accounts or lock unused accounts",
            },
            {
                "id": "root_uid_unique",
                "name": "Only root has UID 0",
                "command": "awk -F: '$3 == 0 {print $1}' /etc/passwd | wc -l",
                "expect_contains": "1",
                "severity": "critical",
                "remediation": "Remove non-root accounts with UID 0",
            },
            {
                "id": "password_max_days",
                "name": "Password max age configured",
                "command": "grep '^PASS_MAX_DAYS' /etc/login.defs | awk '{print $2}'",
                "expect_not": "99999",
                "severity": "medium",
                "remediation": "Set PASS_MAX_DAYS to 90 or less in /etc/login.defs",
            },
        ],
    },
    "filesystem": {
        "name": "Filesystem Security",
        "description": "Check filesystem permissions and mount options",
        "tasks": [
            {
                "id": "tmp_noexec",
                "name": "/tmp mounted with noexec",
                "command": "mount | grep ' /tmp ' | grep -c noexec || echo 0",
                "expect_not": "0",
                "severity": "medium",
                "remediation": "Mount /tmp with noexec,nosuid,nodev options",
            },
            {
                "id": "world_writable",
                "name": "No world-writable files in system dirs",
                "command": "find /usr /etc -maxdepth 2 -perm -0002 -type f 2>/dev/null | head -5 | wc -l",
                "expect_contains": "0",
                "severity": "high",
                "remediation": "Remove world-writable permissions from system files",
            },
        ],
    },
    "services": {
        "name": "Unnecessary Services",
        "description": "Check that unnecessary or insecure services are disabled",
        "tasks": [
            {
                "id": "telnet_disabled",
                "name": "Telnet not running",
                "command": "systemctl is-active telnet.socket telnet xinetd 2>/dev/null | grep -c active || echo 0",
                "expect_contains": "0",
                "severity": "critical",
                "remediation": "Disable and stop telnet service; use SSH instead",
            },
            {
                "id": "ntp_running",
                "name": "Time synchronization active",
                "command": "systemctl is-active chronyd ntpd systemd-timesyncd 2>/dev/null | grep -c active || echo 0",
                "expect_not": "0",
                "severity": "medium",
                "remediation": "Enable chronyd or systemd-timesyncd for time synchronization",
            },
        ],
    },
    "updates": {
        "name": "System Updates",
        "description": "Check system update status",
        "tasks": [
            {
                "id": "security_updates",
                "name": "No pending security updates",
                "command": (
                    "if command -v apt-get &>/dev/null; then "
                    "apt-get -s upgrade 2>/dev/null | grep -c '^Inst.*security' || echo 0; "
                    "elif command -v yum &>/dev/null; then "
                    "yum check-update --security 2>/dev/null | tail -1 | wc -l || echo 0; "
                    "else echo 'unknown'; fi"
                ),
                "expect_contains": "0",
                "severity": "high",
                "remediation": "Apply pending security updates",
            },
        ],
    },
}

_SCAN_PLAYBOOK_TEMPLATE = textwrap.dedent("""\
---
- name: "Compliance scan: {scan_name}"
  hosts: "{hosts}"
  gather_facts: false
  become: {become}
  tasks:
{tasks_yaml}
""")


class ComplianceScanner(BaseTool):
    @property
    def name(self) -> str:
        return "scan_compliance"

    @property
    def description(self) -> str:
        return (
            "Run security and compliance checks against hosts. Built-in scan profiles: "
            "ssh_hardening, firewall, user_security, filesystem, services, updates. "
            "Can also run custom checks defined as a list of commands with expected output. "
            "Returns pass/fail per check per host with severity and remediation hints."
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
                "host_pattern": {
                    "type": "string",
                    "description": "Host or group pattern to scan (default: 'all')",
                },
                "profiles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "List of scan profiles to run. Available: "
                        "ssh_hardening, firewall, user_security, filesystem, services, updates. "
                        "Use ['all'] to run everything."
                    ),
                },
                "custom_checks": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "name": {"type": "string"},
                            "command": {"type": "string"},
                            "expect_contains": {"type": "string"},
                            "expect_not": {"type": "string"},
                            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                            "remediation": {"type": "string"},
                        },
                        "required": ["id", "name", "command"],
                    },
                    "description": "Custom compliance checks (command + expected output)",
                },
            },
            "required": ["workspace_path", "inventory"],
        }

    @staticmethod
    def _resolve_inventory(ws: Path, inventory: str) -> Path:
        stripped = inventory.removeprefix("inventory/").removeprefix("inventory\\")
        candidates = [ws / "inventory" / stripped, ws / inventory, ws / "inventory" / inventory]
        for c in candidates:
            if c.exists():
                return c
        return candidates[0]

    def _collect_checks(
        self,
        profiles: list[str] | None,
        custom_checks: list[dict[str, Any]] | None,
    ) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        selected = profiles or ["all"]
        if "all" in selected:
            selected = list(BUILTIN_CHECKS.keys())

        for profile_name in selected:
            profile = BUILTIN_CHECKS.get(profile_name)
            if profile:
                for task in profile["tasks"]:
                    checks.append({**task, "profile": profile_name})

        if custom_checks:
            for check in custom_checks:
                checks.append({**check, "profile": "custom"})

        return checks

    def _build_playbook(self, checks: list[dict[str, Any]], hosts: str, become: bool) -> str:
        tasks: list[dict[str, Any]] = []
        for check in checks:
            tasks.append({
                "name": f"CHECK: {check['name']} [{check.get('id', 'unknown')}]",
                "ansible.builtin.shell": check["command"],
                "register": f"check_{check['id']}",
                "changed_when": False,
                "failed_when": False,
                "ignore_errors": True,
            })

        tasks_yaml = yaml.dump(tasks, default_flow_style=False, indent=2)
        indented = "\n".join(f"    {line}" for line in tasks_yaml.splitlines())

        return _SCAN_PLAYBOOK_TEMPLATE.format(
            scan_name="compliance",
            hosts=hosts,
            become="true" if become else "false",
            tasks_yaml=indented,
        )

    async def execute(
        self,
        workspace_path: str = "",
        inventory: str = "",
        host_pattern: str = "all",
        profiles: list[str] | None = None,
        custom_checks: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ToolResult:
        if not workspace_path or not inventory:
            return ToolResult.fail("workspace_path and inventory are required")

        ws = Path(workspace_path)
        inv_path = self._resolve_inventory(ws, inventory)
        if not inv_path.exists():
            return ToolResult.fail(f"Inventory not found: {inv_path}")

        checks = self._collect_checks(profiles, custom_checks)
        if not checks:
            return ToolResult.fail("No checks to run. Specify profiles or custom_checks.")

        playbook_content = self._build_playbook(checks, host_pattern, become=True)
        scan_playbook = ws / "_compliance_scan.yml"
        scan_playbook.parent.mkdir(parents=True, exist_ok=True)
        scan_playbook.write_text(playbook_content, encoding="utf-8")

        extravars: dict[str, Any] = {}
        session_id = kwargs.get("_session_id")
        if session_id:
            vault = SecretVault.get_instance().for_session(session_id)
            extravars.update(vault.get_all())

        keys_dir = ws / ".tuyere" / "ssh_keys"
        for var_name in list(extravars):
            value = extravars[var_name]
            if not isinstance(value, str):
                continue
            if var_name.lower() in _SSH_KEY_SECRET_NAMES or all(h in value for h in _SSH_KEY_HEADERS):
                keys_dir.mkdir(parents=True, exist_ok=True)
                key_file = keys_dir / var_name
                if key_file.exists():
                    os.chmod(key_file, stat.S_IWUSR | stat.S_IRUSR)
                key_file.write_text(value)
                os.chmod(key_file, stat.S_IRUSR | stat.S_IWUSR)
                extravars[var_name] = str(key_file)

        env_dir = ws / ".tuyere" / "env"
        if env_dir.exists():
            for artifact in ("cmdline", "extravars"):
                p = env_dir / artifact
                if p.exists():
                    p.unlink()

        runner_kwargs: dict[str, Any] = {
            "private_data_dir": str(ws / ".tuyere"),
            "project_dir": str(ws),
            "playbook": "_compliance_scan.yml",
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
                timeout=300,
            )
        except TimeoutError:
            return ToolResult.fail(
                "Security scan timed out after 5 minutes. "
                "Some hosts may be slow to respond or unreachable."
            )
        finally:
            scan_playbook.unlink(missing_ok=True)

        check_map = {f"check_{c['id']}": c for c in checks}
        results_by_host: dict[str, list[dict[str, Any]]] = {}

        for event in result.events:
            if event.get("event") not in ("runner_on_ok", "runner_on_failed", "runner_on_unreachable"):
                continue
            ed = event.get("event_data", {})
            host = ed.get("host", "unknown")
            task_name = ed.get("task", "")
            res = ed.get("res", {})

            check_id_match = None
            for cid, cdata in check_map.items():
                if cdata.get("id", "") in task_name or cdata.get("name", "") in task_name:
                    check_id_match = cid
                    break

            if not check_id_match:
                continue

            check = check_map[check_id_match]
            stdout = (res.get("stdout", "") or "").strip()
            rc = res.get("rc", -1)

            passed = True
            reason = ""
            if check.get("expect_contains"):
                if check["expect_contains"] not in stdout:
                    passed = False
                    reason = f"Expected '{check['expect_contains']}' in output, got: {stdout[:200]}"
            if check.get("expect_not"):
                if check["expect_not"] in stdout:
                    passed = False
                    reason = f"Found disallowed value '{check['expect_not']}' in output: {stdout[:200]}"
            if rc != 0 and event.get("event") == "runner_on_failed":
                passed = False
                reason = reason or f"Command failed with rc={rc}"

            results_by_host.setdefault(host, []).append({
                "check_id": check.get("id", ""),
                "name": check.get("name", ""),
                "profile": check.get("profile", ""),
                "severity": check.get("severity", "medium"),
                "status": "PASS" if passed else "FAIL",
                "output": stdout[:300],
                "reason": reason,
                "remediation": check.get("remediation", "") if not passed else "",
            })

        if not results_by_host:
            return ToolResult.fail(
                "Security scan could not reach any hosts. "
                "Verify that hosts are reachable and credentials are correct."
            )

        total_pass = sum(1 for h in results_by_host.values() for r in h if r["status"] == "PASS")
        total_fail = sum(1 for h in results_by_host.values() for r in h if r["status"] == "FAIL")
        critical_fails = sum(
            1 for h in results_by_host.values()
            for r in h if r["status"] == "FAIL" and r["severity"] in ("critical", "high")
        )

        return ToolResult.ok(
            output=(
                f"Security scan complete: {total_pass} checks passed, {total_fail} failed "
                f"({critical_fails} high-priority issues) across {len(results_by_host)} host(s)."
            ),
            results=results_by_host,
            summary={
                "total_checks": total_pass + total_fail,
                "passed": total_pass,
                "failed": total_fail,
                "critical_failures": critical_fails,
                "hosts_scanned": len(results_by_host),
            },
        )
