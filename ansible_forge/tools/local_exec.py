"""Local command execution tool — last-resort shell commands on the host.

This tool exists ONLY for operations that have no Ansible module or Terraform
resource equivalent.  A guardrail layer inspects every command and rejects
those that should use run_adhoc / generate_playbook / terraform_exec instead,
returning an actionable error with the correct Ansible module to use.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Any

from ansible_forge.logging import get_logger
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-[^\s]*r[^\s]*\s+/\s*$"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+.*of=/dev/"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\b:(){ :\|:& };:"),
]

_ANSIBLE_REDIRECT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\baws\s+ec2\b"), "run_adhoc with amazon.aws.ec2_instance_info / ec2_vpc_net_info"),
    (re.compile(r"\baws\s+s3\b"), "run_adhoc with amazon.aws.s3_bucket or amazon.aws.s3_object"),
    (re.compile(r"\baws\s+route53\b"), "run_adhoc with amazon.aws.route53 / route53_info"),
    (re.compile(r"\baws\s+iam\b"), "run_adhoc with amazon.aws.iam_role / iam_user / iam_policy"),
    (re.compile(r"\baws\s+elbv?2?\b"), "run_adhoc with amazon.aws.elb_application_lb_info"),
    (re.compile(r"\baws\s+service-quotas\b"), "run_adhoc with ansible.builtin.command on localhost (wrap in a playbook with changed_when: false)"),
    (re.compile(r"\baws\s+sts\b"), "run_adhoc with amazon.aws.sts_caller_identity (amazon.aws collection)"),
    (re.compile(r"\baws\s+configure\b"), "request_secret for AWS credentials — never configure CLI directly"),
    (re.compile(r"\baws\s+"), "run_adhoc with the appropriate amazon.aws.* module"),
    (re.compile(r"\baz\s+"), "run_adhoc with the appropriate azure.azcollection.* module"),
    (re.compile(r"\bgcloud\s+"), "run_adhoc with the appropriate google.cloud.* module"),
    (re.compile(r"\bkubectl\s+"), "run_adhoc with kubernetes.core.k8s_info / k8s module"),
    (re.compile(r"\bhelm\s+"), "run_adhoc with kubernetes.core.helm / helm_info module"),
    (re.compile(r"\bpip3?\s+install\b"), "run_adhoc with ansible.builtin.pip module"),
    (re.compile(r"\bbrew\s+install\b"), "run_adhoc with ansible.builtin.homebrew module"),
    (re.compile(r"\bapt\s+install\b|\bapt-get\s+install\b"), "run_adhoc with ansible.builtin.apt module"),
    (re.compile(r"\bdnf\s+install\b|\byum\s+install\b"), "run_adhoc with ansible.builtin.dnf / yum module"),
    (re.compile(r"\bsystemctl\s+"), "run_adhoc with ansible.builtin.systemd module"),
    (re.compile(r"\bcurl\s+.*https?://"), "run_adhoc with ansible.builtin.uri (API) or ansible.builtin.get_url (download)"),
    (re.compile(r"\bwget\s+"), "run_adhoc with ansible.builtin.get_url module"),
    (re.compile(r"\bssh-keygen\b"), "run_adhoc with community.crypto.openssh_keypair module"),
    (re.compile(r"\bssh-keyscan\b"), "run_adhoc with ansible.builtin.known_hosts module"),
    (re.compile(r"\bssh\s+"), "run_adhoc with ansible.builtin.ping or test_connectivity tool"),
    (re.compile(r"\bdocker\s+(?!ps|inspect)"), "run_adhoc with community.docker.* modules"),
    (re.compile(r"\bterraform\s+"), "terraform_exec tool (not local_exec)"),
    (re.compile(r"\bopenshift-install\b"), "run_adhoc with ansible.builtin.command on localhost (wrap with async, environment, changed_when)"),
    (re.compile(r"\boc\s+(?:get|create|apply|delete|adm)\b"), "run_adhoc with kubernetes.core.k8s / k8s_info module"),
    (re.compile(r"\bansible-galaxy\b"), "manage_galaxy tool (not local_exec)"),
    (re.compile(r"\bansible-playbook\b"), "execute_playbook tool (not local_exec)"),
    (re.compile(r"\bansible\s+"), "run_adhoc tool (not local_exec)"),
]

_ALLOWED_PATTERNS = [
    re.compile(r"\btart\s+"),
    re.compile(r"\bvagrant\s+"),
    re.compile(r"^\s*ps\s+"),
    re.compile(r"\bps\s+aux\b"),
    re.compile(r"\blsof\s+"),
    re.compile(r"\bpgrep\b|\bpkill\b"),
    re.compile(r"\bping\s+"),
    re.compile(r"\buname\b"),
    re.compile(r"\bsw_vers\b"),
    re.compile(r"\bwhich\b"),
    re.compile(r"\bwhoami\b"),
    re.compile(r"\bls\b"),
    re.compile(r"\bcat\s+/etc/os-release"),
    re.compile(r"\bdf\b"),
    re.compile(r"\bfree\b"),
    re.compile(r"\buptime\b"),
    re.compile(r"\bhostname\b"),
    re.compile(r"\bdocker\s+(?:ps|inspect)\b"),
    re.compile(r"\bmkdir\b"),
    re.compile(r"--version\b"),
    re.compile(r"\bdig\s+"),
    re.compile(r"\bnslookup\b"),
]

MAX_OUTPUT_BYTES = 256_000
DEFAULT_TIMEOUT = 120


class LocalExec(BaseTool):
    @property
    def name(self) -> str:
        return "local_exec"

    @property
    def description(self) -> str:
        return (
            "LAST RESORT — run a shell command on the local machine. "
            "ONLY for: Tart/Vagrant VM lifecycle, checking running processes "
            "(ps, lsof), or quick diagnostics (ping, uname). "
            "REJECTED for: AWS/Azure/GCP CLI calls, package installs (pip/brew/apt), "
            "curl/wget downloads, kubectl/helm, ssh commands, terraform, or anything "
            "with an Ansible module equivalent. Use run_adhoc, generate_playbook, "
            "or terraform_exec instead."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "working_directory": {
                    "type": "string",
                    "description": "Optional working directory. Defaults to the session workspace.",
                },
                "timeout": {
                    "type": "integer",
                    "description": f"Timeout in seconds. Default {DEFAULT_TIMEOUT}.",
                },
            },
            "required": ["command"],
        }

    @staticmethod
    def _check_ansible_redirect(command: str) -> str | None:
        for allow in _ALLOWED_PATTERNS:
            if allow.search(command):
                return None
        for pattern, redirect in _ANSIBLE_REDIRECT:
            if pattern.search(command):
                return redirect
        return None

    async def execute(self, **kwargs: Any) -> ToolResult:
        command: str = kwargs.get("command", "").strip()
        if not command:
            return ToolResult.fail("No command provided.")

        for pattern in _DANGEROUS_PATTERNS:
            if pattern.search(command):
                return ToolResult.fail(
                    "Command blocked by safety filter: matches dangerous pattern."
                )

        redirect = self._check_ansible_redirect(command)
        if redirect:
            logger.warning(
                "local_exec_redirected",
                command=command[:200],
                redirect=redirect,
            )
            return ToolResult.fail(
                f"BLOCKED: This command has an Ansible/Terraform equivalent. "
                f"Use {redirect} instead. "
                f"local_exec is only for Tart/Vagrant VM lifecycle and process "
                f"diagnostics (ps, lsof, ping). The TOOL HIERARCHY rule requires "
                f"Ansible modules first, Terraform second, local_exec dead last."
            )

        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 600)
        cwd = kwargs.get("working_directory") or kwargs.get("_workspace_path")

        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"

        logger.info("local_exec_start", command=command[:200], cwd=cwd, timeout=timeout)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except TimeoutError:
            try:
                proc.kill()
                await proc.wait()
            except Exception:
                pass
            return ToolResult.fail(f"Command timed out after {timeout}s: {command[:100]}")
        except FileNotFoundError:
            return ToolResult.fail(f"Working directory not found: {cwd}")
        except Exception as exc:
            return ToolResult.fail(f"Failed to execute: {exc}")

        stdout = stdout_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = stderr_bytes.decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        exit_code = proc.returncode or 0

        logger.info(
            "local_exec_done",
            command=command[:200],
            exit_code=exit_code,
            stdout_len=len(stdout),
            stderr_len=len(stderr),
        )

        if exit_code != 0:
            combined = stdout
            if stderr:
                combined = f"{stdout}\n--- stderr ---\n{stderr}" if stdout else stderr
            return ToolResult.fail(
                f"Exit code {exit_code}",
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                combined_output=combined,
            )

        return ToolResult.ok(
            output=stdout or "(no output)",
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
        )
