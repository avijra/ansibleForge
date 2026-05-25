"""Local command execution tool — last-resort shell on the host.

Commands are checked against a BLOCKED list (destructive operations) and a
REDIRECT list (Ansible/Terraform CLIs that have dedicated tools).  Redirected
commands are allowed through ONLY when the agent's execution tools have already
failed 2+ times in the session (_exec_fail_count escape hatch), preventing
tool deadlock while keeping Ansible/Terraform as the default path.
"""

from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Any

from ansible_forge.config import get_settings
from ansible_forge.logging import get_logger
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.tools.base import BaseTool, ToolResult

logger = get_logger(__name__)

_DANGEROUS_PATTERNS = [
    re.compile(r"\brm\s+-[^\s]*r[^\s]*\s+/\s*$"),
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\s+.*of=/dev/"),
    re.compile(r">\s*/dev/sd"),
    re.compile(r"\b:(){ :\|:& };:"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bshutdown\b|\bpoweroff\b|\bhalt\b"),
    re.compile(r"\bvi\b|\bvim\b|\bnano\b|\bed\b"),
]

_VERSION_RE = re.compile(r"^\s*\S+\s+(?:--?version|-V|version)\s*$")

_ANSIBLE_REDIRECT: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\baws\s+ec2\b"), "run_adhoc with amazon.aws.ec2_instance_info / ec2_vpc_net_info"),
    (re.compile(r"\baws\s+s3\b"), "run_adhoc with amazon.aws.s3_bucket or amazon.aws.s3_object"),
    (re.compile(r"\baws\s+route53\b"), "run_adhoc with amazon.aws.route53 / route53_info"),
    (re.compile(r"\baws\s+iam\b"), "run_adhoc with amazon.aws.iam_role / iam_user / iam_policy"),
    (re.compile(r"\baws\s+elbv?2?\b"), "run_adhoc with amazon.aws.elb_application_lb_info"),
    (re.compile(r"\baws\s+service-quotas\b"), "run_adhoc with ansible.builtin.command on localhost"),
    (re.compile(r"\baws\s+sts\b"), "run_adhoc with amazon.aws.sts_caller_identity"),
    (re.compile(r"\baws\s+configure\b"), "request_secret for AWS credentials"),
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
    (re.compile(r"\bcurl\s+.*https?://"), "run_adhoc with ansible.builtin.uri or ansible.builtin.get_url"),
    (re.compile(r"\bwget\s+"), "run_adhoc with ansible.builtin.get_url module"),
    (re.compile(r"\bssh-keygen\b"), "run_adhoc with community.crypto.openssh_keypair module"),
    (re.compile(r"\bssh-keyscan\b"), "run_adhoc with ansible.builtin.known_hosts module"),
    (re.compile(r"\bssh\s+"), "run_adhoc with ansible.builtin.ping or test_connectivity tool"),
    (re.compile(r"\bdocker\s+(?!ps|inspect)"), "run_adhoc with community.docker.* modules"),
    (re.compile(r"\bterraform\s+"), "terraform_exec tool (not local_exec)"),
    (re.compile(r"\bopenshift-install\b"), "run_adhoc with ansible.builtin.command on localhost"),
    (re.compile(r"\boc\s+(?:get|create|apply|delete|adm)\b"), "run_adhoc with kubernetes.core.k8s / k8s_info module"),
    (re.compile(r"\bansible-galaxy\b"), "manage_galaxy tool (not local_exec)"),
    (re.compile(r"\bansible-playbook\b"), "execute_playbook tool (not local_exec)"),
    (re.compile(r"\bansible\s+(?!--version)"), "run_adhoc tool (not local_exec)"),
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

_ESCAPE_HATCH_THRESHOLD = 2


def _is_self_harm(command: str) -> bool:
    """Return True if the command would kill or disrupt the Tuyere backend."""
    pid_str = str(os.getpid())
    ppid_str = str(os.getppid())
    port_str = str(get_settings().port)

    kill_pid = re.compile(
        rf"\bkill\s+(?:-\w+\s+)*(?:{re.escape(pid_str)}|{re.escape(ppid_str)})\b"
    )
    if kill_pid.search(command):
        return True

    kill_via_port = re.compile(
        rf"(?:\blsof\b.*-[^\s]*i\s*:\s*{re.escape(port_str)}\b.*\b(?:kill|xargs\s+kill)\b)"
        rf"|(?:\bkill\b.*\$\(.*\blsof\b.*:\s*{re.escape(port_str)}\b)"
        rf"|(?:\bkill\b.*`.*\blsof\b.*:\s*{re.escape(port_str)}\b)"
        rf"|(?:\bfuser\b.*{re.escape(port_str)}/tcp.*-k)"
        rf"|(?:\bfuser\b.*-k.*{re.escape(port_str)}/tcp)"
    )
    if kill_via_port.search(command):
        return True

    process_kill_by_name = re.compile(
        r"\b(?:pkill|killall)\b.*\b(?:ansibleforge|ansible.forge|tuyere|uvicorn)\b",
        re.IGNORECASE,
    )
    return bool(process_kill_by_name.search(command))

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
            "Allowed: Tart/Vagrant VM lifecycle, process inspection (ps, lsof, pgrep, pkill), "
            "version checks (--version), DNS lookups (dig, nslookup), system info "
            "(uname, hostname, df, free, uptime, whoami, sw_vers), directory creation (mkdir), "
            "file listing (ls), docker inspection (docker ps, docker inspect), and ping. "
            "BLOCKED: All cloud/infrastructure CLI commands (aws, az, gcloud, kubectl, helm, "
            "terraform, curl, wget, systemctl, apt/yum/dnf, ansible-*) are redirected to "
            "dedicated Ansible/Terraform tools. The block lifts after 2+ Ansible/Terraform "
            "execution failures in the session."
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
        stripped = segment.strip()
        if not stripped:
            return None

        if _VERSION_RE.match(stripped):
            return None

        for pattern in _ALLOWED_PATTERNS:
            if pattern.search(stripped):
                return None

        for pattern, redirect in _ANSIBLE_REDIRECT:
            if pattern.search(stripped):
                return redirect

        return None

    @staticmethod
    def _check_command(command: str) -> str | None:
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

        if _is_self_harm(command):
            _port = get_settings().port
            _pid = os.getpid()
            return ToolResult.fail(
                f"BLOCKED: this command would kill the Tuyere backend process "
                f"(PID {_pid}, port {_port}). "
                f"Port {_port} is YOUR OWN backend — killing it kills the app. "
                f"ansible-runner does NOT need port {_port}; "
                f"it runs as a subprocess, not a server."
            )

        exec_fail_count: int = kwargs.get("_exec_fail_count", 0)

        rejection = self._check_command(command)
        if rejection:
            if exec_fail_count >= _ESCAPE_HATCH_THRESHOLD:
                logger.warning(
                    "local_exec_escape_hatch",
                    command=command[:200],
                    redirect=rejection[:200],
                    exec_fail_count=exec_fail_count,
                )
            else:
                logger.warning(
                    "local_exec_blocked",
                    command=command[:200],
                    reason=rejection[:200],
                )
                return ToolResult.fail(
                    f"Use `{rejection.split()[0]}` instead: {rejection}. "
                    f"Do not surface this message to the user."
                )

        timeout = max(10, min(kwargs.get("timeout", DEFAULT_TIMEOUT) or DEFAULT_TIMEOUT, 600))
        cwd = kwargs.get("working_directory") or kwargs.get("_workspace_path")

        env = os.environ.copy()
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"

        session_id = kwargs.get("_session_id")
        if session_id:
            try:
                vault = SecretVault.get_instance().for_session(session_id)
                for key, value in vault.get_all().items():
                    if key.isupper() or key.startswith("AWS_") or key.startswith("ARM_") or key.startswith("GOOGLE_"):
                        env[key] = str(value)
            except Exception:
                logger.debug("vault_inject_failed", exc_info=True)

        live_queue: asyncio.Queue | None = kwargs.get("_live_log_queue")

        logger.info("local_exec_start", command=command[:200], cwd=cwd, timeout=timeout)

        proc = None
        stdout_parts: list[bytes] = []
        stderr_parts: list[bytes] = []
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                env=env,
            )

            async def _stream_pipe(
                pipe: asyncio.StreamReader, parts: list[bytes], is_stderr: bool = False,
            ) -> None:
                total = 0
                while True:
                    line = await pipe.readline()
                    if not line:
                        break
                    parts.append(line)
                    total += len(line)
                    if total > MAX_OUTPUT_BYTES:
                        break
                    if live_queue is not None:
                        decoded = line.decode("utf-8", errors="replace").rstrip("\n\r")
                        if decoded.strip():
                            import contextlib
                            with contextlib.suppress(Exception):
                                live_queue.put_nowait({
                                    "type": "stderr_line" if is_stderr else "shell_output",
                                    "line": decoded[:500],
                                })

            log_watcher: asyncio.Task[None] | None = None
            if live_queue is not None and cwd:
                from ansible_forge.tools._log_tailer import snapshot_log_files, tail_new_logs
                log_snapshot = snapshot_log_files(Path(cwd))
                log_watcher = asyncio.create_task(
                    tail_new_logs(Path(cwd), log_snapshot, live_queue)
                )

            assert proc.stdout is not None
            assert proc.stderr is not None
            try:
                await asyncio.wait_for(
                    asyncio.gather(
                        _stream_pipe(proc.stdout, stdout_parts),
                        _stream_pipe(proc.stderr, stderr_parts, is_stderr=True),
                        proc.wait(),
                    ),
                    timeout=timeout,
                )
            finally:
                if log_watcher and not log_watcher.done():
                    log_watcher.cancel()
                    import contextlib as _ctxlib
                    with _ctxlib.suppress(asyncio.CancelledError):
                        await log_watcher
        except asyncio.CancelledError:
            if proc is not None:
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

        stdout = b"".join(stdout_parts).decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
        stderr = b"".join(stderr_parts).decode("utf-8", errors="replace")[:MAX_OUTPUT_BYTES]
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
