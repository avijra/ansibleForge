"""Local command execution tool — last-resort shell commands on the host.

DEFAULT-DENY architecture: every command is split on shell operators
(&&, ||, ;, |) and each segment must either match the narrow allow-list
or be rejected.  Redirect patterns (Ansible/Terraform equivalents) are
checked BEFORE the allow-list — a compound command cannot sneak a
redirectable segment past the guardrail by prepending an allowed one.
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

_VERSION_RE = re.compile(r"^\s*\S+\s+(?:--?version|-V|version)\s*$")

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
    (re.compile(r"\bpip3?\s+"), "run_adhoc with ansible.builtin.pip or ansible.builtin.command on localhost"),
    (re.compile(r"\bbrew\s+install\b"), "run_adhoc with ansible.builtin.homebrew module"),
    (re.compile(r"\bbrew\s+"), "run_adhoc with ansible.builtin.homebrew or ansible.builtin.command on localhost"),
    (re.compile(r"\bapt\s+install\b|\bapt-get\s+install\b"), "run_adhoc with ansible.builtin.apt module"),
    (re.compile(r"\bapt(?:-get)?\s+"), "run_adhoc with ansible.builtin.apt or ansible.builtin.command on localhost"),
    (re.compile(r"\bdnf\s+install\b|\byum\s+install\b"), "run_adhoc with ansible.builtin.dnf / yum module"),
    (re.compile(r"\bdnf\s+|\byum\s+"), "run_adhoc with ansible.builtin.dnf/yum or ansible.builtin.command on localhost"),
    (re.compile(r"\bnpm\s+install\b"), "run_adhoc with ansible.builtin.npm module"),
    (re.compile(r"\bnpm\s+"), "run_adhoc with ansible.builtin.npm or ansible.builtin.command on localhost"),
    (re.compile(r"\bsystemctl\s+"), "run_adhoc with ansible.builtin.systemd module"),
    (re.compile(r"\bservice\s+"), "run_adhoc with ansible.builtin.service module"),
    (re.compile(r"\bcurl\s+"), "run_adhoc with ansible.builtin.uri (API) or ansible.builtin.get_url (download)"),
    (re.compile(r"\bwget\s+"), "run_adhoc with ansible.builtin.get_url module"),
    (re.compile(r"\bssh-keygen\b"), "run_adhoc with community.crypto.openssh_keypair module"),
    (re.compile(r"\bssh-keyscan\b"), "run_adhoc with ansible.builtin.known_hosts module"),
    (re.compile(r"^\s*ssh\s+"), "run_adhoc with ansible.builtin.ping or test_connectivity tool"),
    (re.compile(r"\bdocker\s+(?!ps|inspect)"), "run_adhoc with community.docker.* modules"),
    (re.compile(r"\bterraform\s+"), "terraform_exec tool (not local_exec)"),
    (re.compile(r"\btofu\s+"), "terraform_exec tool (not local_exec)"),
    (re.compile(r"\bopenshift-install\b"), "execute_playbook wrapping ansible.builtin.command with proper timeout"),
    (re.compile(r"\boc\s+(?:get|create|apply|delete|adm)\b"), "run_adhoc with kubernetes.core.k8s / k8s_info module"),
    (re.compile(r"\bansible-galaxy\b"), "manage_galaxy tool (not local_exec)"),
    (re.compile(r"\bansible-playbook\b"), "execute_playbook tool (not local_exec)"),
    (re.compile(r"\bansible\s+"), "run_adhoc tool (not local_exec)"),
    (re.compile(r"\bls\b"), "run_adhoc with ansible.builtin.find or read_file tool"),
    (re.compile(r"\bmkdir\b"), "run_adhoc with ansible.builtin.file module (state=directory)"),
    (re.compile(r"\bchmod\b"), "run_adhoc with ansible.builtin.file module (mode parameter)"),
    (re.compile(r"\bchown\b"), "run_adhoc with ansible.builtin.file module (owner/group)"),
    (re.compile(r"\bchgrp\b"), "run_adhoc with ansible.builtin.file module (group parameter)"),
    (re.compile(r"\bcp\b"), "run_adhoc with ansible.builtin.copy module"),
    (re.compile(r"\bmv\b"), "run_adhoc with ansible.builtin.command (or copy+file absent)"),
    (re.compile(r"\brm\s+"), "run_adhoc with ansible.builtin.file module (state=absent)"),
    (re.compile(r"\bcat\b"), "read_file tool or run_adhoc with ansible.builtin.slurp"),
    (re.compile(r"\btouch\s+"), "run_adhoc with ansible.builtin.file module (state=touch)"),
    (re.compile(r"\bln\s+"), "run_adhoc with ansible.builtin.file module (state=link)"),
    (re.compile(r"\btar\s+"), "run_adhoc with ansible.builtin.unarchive module"),
    (re.compile(r"\bunzip\s+"), "run_adhoc with ansible.builtin.unarchive module"),
    (re.compile(r"\bfind\s+"), "run_adhoc with ansible.builtin.find module"),
    (re.compile(r"\bstat\s+"), "run_adhoc with ansible.builtin.stat module"),
    (re.compile(r"\bping\s+"), "test_connectivity tool or run_adhoc with ansible.builtin.wait_for"),
    (re.compile(r"\bdig\s+"), "run_adhoc with community.general.dig lookup or ansible.builtin.command"),
    (re.compile(r"\bnslookup\b"), "run_adhoc with community.general.dig lookup"),
    (re.compile(r"\buname\b"), "collect_facts tool (ansible_kernel, ansible_architecture)"),
    (re.compile(r"\bhostname\b"), "collect_facts tool (ansible_hostname)"),
    (re.compile(r"\bdf\b"), "collect_facts tool (ansible_mounts) or run_adhoc ansible.builtin.command"),
    (re.compile(r"\bfree\b"), "collect_facts tool (ansible_memtotal_mb)"),
    (re.compile(r"\buptime\b"), "collect_facts tool (ansible_uptime_seconds)"),
    (re.compile(r"\bwhoami\b"), "collect_facts tool (ansible_user_id)"),
    (re.compile(r"\bdu\s+"), "collect_facts (ansible_mounts) or run_adhoc ansible.builtin.command"),
    (re.compile(r"\bscp\b"), "run_adhoc with ansible.builtin.copy (push) or ansible.builtin.fetch (pull)"),
    (re.compile(r"\brsync\b"), "run_adhoc with ansible.posix.synchronize module"),
    (re.compile(r"\bsudo\b"), "run_adhoc with become: true"),
    (re.compile(r"\bcrontab\b"), "run_adhoc with ansible.builtin.cron module"),
    (re.compile(r"\buseradd\b|\badduser\b"), "run_adhoc with ansible.builtin.user module"),
    (re.compile(r"\bgroupadd\b"), "run_adhoc with ansible.builtin.group module"),
    (re.compile(r"\biptables\b"), "run_adhoc with ansible.builtin.iptables module"),
    (re.compile(r"\bfirewall-cmd\b"), "run_adhoc with ansible.posix.firewalld module"),
    (re.compile(r"\bsemanage\b|\bsetsebool\b"), "run_adhoc with ansible.posix.seboolean / selinux module"),
    (re.compile(r"\bmount\s+"), "run_adhoc with ansible.posix.mount module"),
    (re.compile(r"\bumount\s+"), "run_adhoc with ansible.posix.mount module (state=absent)"),
    (re.compile(r"\bjournalctl\b"), "analyze_logs tool or run_adhoc with ansible.builtin.command"),
    (re.compile(r"\bgit\s+"), "manage_git tool"),
    # Database CLIs
    (re.compile(r"\bmysql\b|\bmariadb\b"), "run_adhoc with community.mysql.mysql_db / mysql_user / mysql_query"),
    (re.compile(r"\bpsql\b|\bpg_dump\b|\bpg_restore\b"), "run_adhoc with community.postgresql.postgresql_db / postgresql_user / postgresql_query"),
    (re.compile(r"\bmongo\b|\bmongosh\b|\bmongodump\b|\bmongorestore\b"), "run_adhoc with community.mongodb.mongodb_shell / mongodb_user"),
    (re.compile(r"\bredis-cli\b"), "run_adhoc with community.general.redis or ansible.builtin.command"),
    # Container / orchestration
    (re.compile(r"\bpodman\s+"), "run_adhoc with containers.podman.* modules"),
    (re.compile(r"\bdocker[\s-]compose\b"), "run_adhoc with community.docker.docker_compose_v2 module"),
    (re.compile(r"\bcrictl\s+"), "run_adhoc with kubernetes.core.k8s module"),
    (re.compile(r"\bskopeo\s+"), "run_adhoc with community.docker.docker_image_info or ansible.builtin.command"),
    # Destructive system commands
    (re.compile(r"\breboot\b"), "run_adhoc with ansible.builtin.reboot module"),
    (re.compile(r"\bshutdown\b|\bpoweroff\b|\bhalt\b"), "run_adhoc with ansible.builtin.reboot or ansible.builtin.command"),
    # Interactive editors
    (re.compile(r"\bvi\b|\bvim\b|\bnano\b|\bed\b"), "write_file tool or run_adhoc with ansible.builtin.lineinfile / blockinfile / template"),
    # Archive / compression
    (re.compile(r"\bgzip\b|\bgunzip\b|\bbzip2\b|\bxz\b"), "run_adhoc with ansible.builtin.unarchive or community.general.archive"),
    (re.compile(r"\bzip\s+"), "run_adhoc with community.general.archive module"),
    # System administration
    (re.compile(r"\bsysctl\s+"), "run_adhoc with ansible.posix.sysctl module"),
    (re.compile(r"\bmodprobe\b|\blsmod\b"), "run_adhoc with community.general.modprobe module"),
    (re.compile(r"\btimedatectl\b"), "run_adhoc with community.general.timezone module"),
    (re.compile(r"\bhostnamectl\b"), "run_adhoc with ansible.builtin.hostname module"),
    (re.compile(r"\bnmcli\b|\bifconfig\b"), "collect_facts tool or run_adhoc with ansible.builtin.command"),
    (re.compile(r"\bip\s+(?:addr|route|link)\b"), "collect_facts tool or run_adhoc with ansible.builtin.command"),
    (re.compile(r"\bparted\b|\bfdisk\b"), "run_adhoc with community.general.parted module"),
    (re.compile(r"\blvcreate\b|\bvgcreate\b|\bpvcreate\b"), "run_adhoc with community.general.lvg / lvol module"),
    (re.compile(r"\bmkswap\b|\bswapon\b|\bswapoff\b"), "run_adhoc with ansible.posix.mount module"),
    (re.compile(r"\bmdadm\b"), "run_adhoc with ansible.builtin.command (RAID management)"),
    # Crypto / certificates
    (re.compile(r"\bopenssl\s+"), "run_adhoc with community.crypto.* modules (x509_certificate, openssl_privatekey, etc.)"),
    (re.compile(r"\bcertbot\b"), "run_adhoc with community.crypto.acme_certificate module"),
    (re.compile(r"\bnft\b|\bnftables\b"), "run_adhoc with ansible.builtin.command or firewall module"),
    (re.compile(r"\bfail2ban-client\b"), "run_adhoc with ansible.builtin.command or template config"),
    # Language package managers
    (re.compile(r"\bgem\s+install\b"), "run_adhoc with community.general.gem module"),
    (re.compile(r"\bpython3?\s+\S+\.py\b"), "run_adhoc with ansible.builtin.script module"),
]

_ALLOWED_PATTERNS = [
    re.compile(r"\btart\s+"),
    re.compile(r"\bvagrant\s+"),
    re.compile(r"\bps\s+aux\b"),
    re.compile(r"^\s*ps\s+"),
    re.compile(r"\blsof\s+"),
    re.compile(r"\bpgrep\b"),
    re.compile(r"\bpkill\b"),
    re.compile(r"\bdocker\s+(?:ps|inspect)\b"),
    re.compile(r"\bsw_vers\b"),
    re.compile(r"\bwc\b"),
    re.compile(r"\bhead\s+"),
    re.compile(r"\btail\s+"),
    re.compile(r"\bgrep\s+"),
    re.compile(r"\bsleep\s+"),
    re.compile(r"\becho\s+"),
    re.compile(r"\bdate\b"),
    re.compile(r"\bwhich\s+"),
    re.compile(r"\benv\b"),
    re.compile(r"\bprintenv\b"),
    re.compile(r"\bsort\b"),
    re.compile(r"\bawk\b"),
    re.compile(r"\bsed\s+"),
    re.compile(r"\bcut\s+"),
    re.compile(r"\buniq\b"),
    re.compile(r"\btr\s+"),
    re.compile(r"\bxargs\b"),
    re.compile(r"\btee\s+"),
    re.compile(r"\bjq\b"),
    re.compile(r"\byq\b"),
    re.compile(r"\bkill\s+"),
    re.compile(r"\btrue\b"),
    re.compile(r"\bfalse\b"),
    re.compile(r"\btest\s+"),
    re.compile(r"\bnetstat\b"),
    re.compile(r"\bss\s+"),
    re.compile(r"\bprintf\s+"),
    re.compile(r"\bbasename\b"),
    re.compile(r"\bdirname\b"),
]

_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\|)\s*")

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
            "DEFAULT-DENY: only Tart/Vagrant VM lifecycle and local process "
            "diagnostics (ps, lsof, pgrep) are allowed. Everything else is "
            "BLOCKED and redirected to the correct Ansible module or Terraform "
            "resource. Use run_adhoc, generate_playbook, or terraform_exec instead."
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
    def _check_segment(segment: str) -> str | None:
        """Check a single command segment. Returns redirect message or None."""
        stripped = segment.strip()
        if not stripped:
            return None

        if _VERSION_RE.match(stripped):
            return None

        for pattern, redirect in _ANSIBLE_REDIRECT:
            if pattern.search(stripped):
                return redirect

        for allow in _ALLOWED_PATTERNS:
            if allow.search(stripped):
                return None

        return (
            "BLOCKED (default-deny): this command is not in the local_exec "
            "allow-list. Use run_adhoc with the appropriate Ansible module, "
            "or generate_playbook / terraform_exec. local_exec only permits "
            "Tart/Vagrant VM commands and process diagnostics (ps, lsof, pgrep)."
        )

    @staticmethod
    def _check_command(command: str) -> str | None:
        """Split compound commands and check every segment.
        Returns the first rejection reason, or None if all segments pass."""
        segments = _SPLIT_RE.split(command)
        for seg in segments:
            result = LocalExec._check_segment(seg)
            if result is not None:
                return result
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

        rejection = self._check_command(command)
        if rejection:
            logger.warning(
                "local_exec_blocked",
                command=command[:200],
                reason=rejection[:200],
            )
            return ToolResult.fail(
                f"BLOCKED: {rejection}. "
                f"The TOOL HIERARCHY rule requires Ansible modules first, "
                f"Terraform second, local_exec dead last."
            )

        timeout = min(kwargs.get("timeout", DEFAULT_TIMEOUT), 600)
        cwd = kwargs.get("working_directory") or kwargs.get("_workspace_path")

        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"

        logger.info("local_exec_start", command=command[:200], cwd=cwd, timeout=timeout)

        proc = None
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
        except asyncio.CancelledError:
            if proc is not None:
                import contextlib

                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.debug("cancel_kill_failed", exc_info=True)
            logger.info("local_exec_cancelled", command=command[:200])
            raise
        except TimeoutError:
            if proc is not None:
                try:
                    proc.kill()
                    await proc.wait()
                except Exception:
                    logger.debug("timeout_kill_failed", exc_info=True)
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
