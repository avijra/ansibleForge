"""Execution Environment (EE) runtime helpers.

Centralises all container-based execution logic so that the rest of the
codebase only needs to call ``is_ee_enabled()``, ``apply_ee_kwargs()``,
or ``ee_exec()`` without knowing Docker/Podman specifics.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog

from ansible_forge.config import (
    effective_ee_container_runtime,
    effective_ee_enabled,
    effective_ee_host_mode,
    effective_ee_image,
    effective_ee_remote_host,
)
from ansible_forge.tools.workspace_sync import (
    docker_host_url,
    local_to_remote_path,
    sync_to_remote,
)

logger = structlog.get_logger(__name__)

PullStatus = Literal["idle", "pulling", "ready", "failed"]


@dataclass
class _PullState:
    status: PullStatus = "idle"
    message: str = ""


_pull_state = _PullState()
_pull_lock = threading.Lock()
_pull_task: asyncio.Task[None] | None = None


def is_ee_enabled() -> bool:
    return effective_ee_enabled()


def is_remote_mode() -> bool:
    return is_ee_enabled() and effective_ee_host_mode() == "remote"


def get_ee_image() -> str:
    return effective_ee_image()


def get_container_runtime() -> str:
    return effective_ee_container_runtime()


def get_pull_state() -> dict[str, str | bool]:
    with _pull_lock:
        return {
            "status": _pull_state.status,
            "message": _pull_state.message,
            "image_ready": _pull_state.status == "ready",
        }


def _set_pull_state(status: PullStatus, message: str) -> None:
    with _pull_lock:
        _pull_state.status = status
        _pull_state.message = message


def _runtime_binary() -> str | None:
    rt = get_container_runtime()
    return shutil.which(rt)


def _docker_host_env() -> dict[str, str]:
    if not is_remote_mode():
        return {}
    remote_host = effective_ee_remote_host()
    if not remote_host:
        return {}
    return {"DOCKER_HOST": docker_host_url(remote_host)}


def runner_locale_env() -> dict[str, str]:
    return {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}


def sanitize_runner_envvars(envvars: dict[str, str]) -> dict[str, str]:
    for key in list(envvars):
        if key.startswith("LC_") or key in ("LANG", "LANGUAGE"):
            envvars.pop(key, None)
    envvars.update(runner_locale_env())
    return envvars


def _ee_locale_env() -> dict[str, str]:
    return runner_locale_env()


def _merged_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    merged = os.environ.copy()
    merged.update(_docker_host_env())
    if extra:
        merged.update(extra)
    return merged


def container_runtime_available() -> tuple[bool, str]:
    rt = get_container_runtime()
    binary = shutil.which(rt)
    if binary:
        return True, binary
    return False, f"{rt} not found on PATH"


async def ee_image_available() -> tuple[bool, str]:
    binary = _runtime_binary()
    if not binary:
        return False, f"{get_container_runtime()} not found"
    image = get_ee_image()
    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "image",
            "inspect",
            image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env=_merged_subprocess_env(),
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=30)
        if rc == 0:
            return True, image
        return False, f"Image '{image}' not found on target host"
    except Exception as exc:
        return False, str(exc)


async def pull_ee_image() -> tuple[bool, str]:
    binary = _runtime_binary()
    if not binary:
        _set_pull_state("failed", f"{get_container_runtime()} not found")
        return False, f"{get_container_runtime()} not found"

    if is_remote_mode() and not effective_ee_remote_host():
        message = "Remote host is not configured"
        _set_pull_state("failed", message)
        return False, message

    image = get_ee_image()
    target = "remote host" if is_remote_mode() else "local machine"
    _set_pull_state("pulling", f"Pulling {image} on {target}...")

    try:
        proc = await asyncio.create_subprocess_exec(
            binary,
            "pull",
            image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=_merged_subprocess_env(),
        )
        assert proc.stderr is not None
        stderr_stream = proc.stderr
        stderr_lines: list[str] = []

        async def _read_stderr() -> None:
            while True:
                line = await stderr_stream.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if text:
                    stderr_lines.append(text)
                    _set_pull_state("pulling", text)

        stderr_task = asyncio.create_task(_read_stderr())
        try:
            await asyncio.wait_for(proc.wait(), timeout=900)
        finally:
            await stderr_task

        if proc.returncode == 0:
            message = f"Pulled {image} on {target}"
            _set_pull_state("ready", message)
            return True, message

        detail = "\n".join(stderr_lines[-5:]) or f"Failed to pull {image}"
        _set_pull_state("failed", detail)
        return False, detail
    except TimeoutError:
        message = f"Timed out pulling {image}"
        _set_pull_state("failed", message)
        return False, message
    except Exception as exc:
        message = str(exc)
        _set_pull_state("failed", message)
        return False, message


async def _pull_background() -> None:
    available, _ = await ee_image_available()
    if available:
        ok, verify_msg = await verify_ee_ansible()
        if ok:
            _set_pull_state("ready", f"Image {get_ee_image()} is ready")
        else:
            _set_pull_state("failed", verify_msg)
        return
    success, _ = await pull_ee_image()
    if success:
        ok, verify_msg = await verify_ee_ansible()
        if not ok:
            _set_pull_state("failed", verify_msg)


def schedule_ee_image_pull() -> None:
    global _pull_task
    if not is_ee_enabled():
        return

    with _pull_lock:
        if _pull_state.status == "pulling":
            return
        if _pull_task and not _pull_task.done():
            return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    async def _runner() -> None:
        global _pull_task
        try:
            await _pull_background()
        finally:
            _pull_task = None

    _pull_task = loop.create_task(_runner())


async def ensure_ee_image_pulled() -> None:
    if not is_ee_enabled():
        return
    available, _ = await ee_image_available()
    if available:
        _set_pull_state("ready", f"Image {get_ee_image()} is ready")
        return
    schedule_ee_image_pull()


def build_volume_mounts(ws: Path, remote_ws: str | None = None) -> list[str]:
    mounts: list[str] = []

    if is_remote_mode():
        remote_path = remote_ws or ws.as_posix()
        mounts.append(f"{remote_path}:{remote_path}:Z")
        return mounts

    mounts.append(f"{ws}:{ws}:Z")

    ansibleforge_dir = Path.home() / ".ansibleforge"
    if ansibleforge_dir.is_dir():
        mounts.append(f"{ansibleforge_dir}:{ansibleforge_dir}:Z")

    tuyere_dir = Path.home() / ".tuyere"
    if tuyere_dir.is_dir():
        mounts.append(f"{tuyere_dir}:{tuyere_dir}:Z")

    ansible_dir = Path.home() / ".ansible"
    if ansible_dir.is_dir():
        mounts.append(f"{ansible_dir}:{ansible_dir}:Z")

    ssh_dir = Path.home() / ".ssh"
    if ssh_dir.is_dir():
        mounts.append(f"{ssh_dir}:{ssh_dir}:ro,Z")

    gitconfig = Path.home() / ".gitconfig"
    if gitconfig.is_file():
        mounts.append(f"{gitconfig}:{gitconfig}:ro,Z")

    return mounts


async def prepare_ee_workspace(ws: Path) -> str | None:
    if not is_remote_mode():
        return None
    if not effective_ee_remote_host():
        raise RuntimeError("Remote host is not configured")
    return await sync_to_remote(ws)


def apply_ee_kwargs(
    runner_kwargs: dict[str, Any],
    ws: Path,
    remote_ws: str | None = None,
) -> dict[str, Any]:
    """Inject EE container isolation kwargs into an ansible-runner call."""
    if not is_ee_enabled():
        return runner_kwargs

    runner_kwargs["process_isolation"] = True
    runner_kwargs["process_isolation_executable"] = get_container_runtime()
    runner_kwargs["container_image"] = get_ee_image()
    effective_remote_ws = remote_ws
    if is_remote_mode() and not effective_remote_ws:
        from ansible_forge.tools.workspace_sync import remote_workspace_path

        effective_remote_ws = remote_workspace_path(ws)
    runner_kwargs["container_volume_mounts"] = build_volume_mounts(
        ws,
        remote_ws=effective_remote_ws,
    )

    envvars = runner_kwargs.get("envvars", {})
    envvars.pop("PYTHONHOME", None)
    envvars.pop("PYTHONPATH", None)
    envvars.pop("ANSIBLE_PYTHON_INTERPRETER", None)
    envvars.update(_docker_host_env())
    if is_ee_enabled():
        sanitize_runner_envvars(envvars)
    runner_kwargs["envvars"] = envvars

    return runner_kwargs


async def verify_ee_ansible() -> tuple[bool, str]:
    if not is_ee_enabled():
        return True, "Execution environment disabled"

    pull = get_pull_state()
    if pull["status"] == "pulling":
        return False, "EE image is still downloading"
    if pull["status"] == "failed":
        available, _ = await ee_image_available()
        if not available:
            message = str(pull.get("message") or "EE image unavailable")
            return False, message

    rc, stdout, stderr = await ee_exec(["ansible", "--version"], timeout=60)
    combined = (stderr or stdout or "").strip()
    if rc != 0:
        detail = combined[:400] or f"ansible --version exited with code {rc}"
        if "locale" in detail.lower():
            return False, f"EE locale misconfigured: {detail}"
        return False, f"EE ansible check failed: {detail}"

    version_line = (stdout or stderr).strip().splitlines()[0] if combined else "ansible available"
    return True, version_line


async def test_remote_connection() -> tuple[bool, str]:
    remote_host = effective_ee_remote_host()
    if not remote_host:
        return False, "Remote host is not configured"

    from ansible_forge.tools.workspace_sync import normalize_ssh_host

    host = normalize_ssh_host(remote_host)
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        host,
        "docker info --format '{{.ServerVersion}}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=20)
    if proc.returncode != 0:
        detail = stderr_b.decode(errors="replace").strip() or "SSH or Docker check failed"
        return False, detail
    version = stdout_b.decode(errors="replace").strip()
    return True, f"Connected to {host} (Docker {version or 'available'})"


async def ee_exec(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    ws: Path | None = None,
) -> tuple[int, str, str]:
    """Execute a command inside the EE container."""
    if not is_ee_enabled():
        import sys

        merged_env: dict[str, str] | None = None
        if env:
            merged_env = os.environ.copy()
            merged_env.update(env)
        if getattr(sys, "frozen", False):
            if merged_env is None:
                merged_env = os.environ.copy()
            merged_env.pop("PYTHONHOME", None)
            merged_env.pop("PYTHONPATH", None)

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd) if cwd else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
        except asyncio.CancelledError:
            proc.kill()
            await proc.wait()
            raise
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 1, "", f"Command timed out after {timeout}s"
        return (
            proc.returncode or 0,
            stdout_b.decode(errors="replace"),
            stderr_b.decode(errors="replace"),
        )

    pull = get_pull_state()
    if pull["status"] == "pulling":
        return 1, "", "Execution environment image is still downloading. Try again shortly."
    if pull["status"] == "failed":
        available, _ = await ee_image_available()
        if not available:
            return 1, "", f"Execution environment image unavailable: {pull['message']}"

    binary = _runtime_binary()
    if not binary:
        return 1, "", f"{get_container_runtime()} not found on PATH"

    mount_ws = ws or cwd
    remote_ws: str | None = None
    effective_cwd = cwd

    if is_remote_mode():
        if not mount_ws:
            return 1, "", "Remote EE execution requires a workspace path"
        if not effective_ee_remote_host():
            return 1, "", "Remote host is not configured"
        try:
            remote_ws = await sync_to_remote(Path(mount_ws))
        except Exception as exc:
            return 1, "", f"Workspace sync failed: {exc}"
        if cwd:
            effective_cwd = local_to_remote_path(cwd, Path(mount_ws), remote_ws)

    container_cmd: list[str] = [binary, "run", "--rm"]

    if mount_ws:
        for mount in build_volume_mounts(Path(mount_ws), remote_ws=remote_ws):
            container_cmd.extend(["-v", mount])
    if effective_cwd:
        container_cmd.extend(["-w", str(effective_cwd)])

    for key, val in _ee_locale_env().items():
        container_cmd.extend(["-e", f"{key}={val}"])

    if env:
        for key, val in env.items():
            container_cmd.extend(["-e", f"{key}={val}"])

    _passthrough_vars = (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "AWS_PROFILE",
        "ARM_CLIENT_ID",
        "ARM_CLIENT_SECRET",
        "ARM_TENANT_ID",
        "ARM_SUBSCRIPTION_ID",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_CLOUD_PROJECT",
        "TF_VAR_",
        "ANSIBLE_",
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "HCLOUD_TOKEN",
        "DIGITALOCEAN_TOKEN",
        "DO_API_TOKEN",
    )
    for key, val in os.environ.items():
        if any(key.startswith(p) or key == p for p in _passthrough_vars) and (
            not env or key not in env
        ):
            container_cmd.extend(["-e", f"{key}={val}"])

    container_cmd.append(get_ee_image())
    container_cmd.extend(cmd)

    logger.debug("ee_exec", cmd=container_cmd)

    proc = await asyncio.create_subprocess_exec(
        *container_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_merged_subprocess_env(env),
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
    except asyncio.CancelledError:
        proc.kill()
        await proc.wait()
        raise
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return 1, "", f"Container command timed out after {timeout}s"
    return (
        proc.returncode or 0,
        stdout_b.decode(errors="replace"),
        stderr_b.decode(errors="replace"),
    )
