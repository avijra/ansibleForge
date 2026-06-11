"""Execution Environment (EE) runtime helpers.

Centralises all container-based execution logic so that the rest of the
codebase only needs to call ``is_ee_enabled()``, ``apply_ee_kwargs()``,
or ``ee_exec()`` without knowing Docker/Podman specifics.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import structlog

from ansible_forge.config import (
    effective_ee_container_runtime,
    effective_ee_enabled,
    effective_ee_image,
)

logger = structlog.get_logger(__name__)


def is_ee_enabled() -> bool:
    return effective_ee_enabled()


def get_ee_image() -> str:
    return effective_ee_image()


def get_container_runtime() -> str:
    return effective_ee_container_runtime()


def _runtime_binary() -> str | None:
    rt = get_container_runtime()
    return shutil.which(rt)


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
            binary, "image", "inspect", image,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=15)
        if rc == 0:
            return True, image
        return False, f"Image '{image}' not found locally"
    except Exception as exc:
        return False, str(exc)


async def pull_ee_image() -> tuple[bool, str]:
    binary = _runtime_binary()
    if not binary:
        return False, f"{get_container_runtime()} not found"
    image = get_ee_image()
    try:
        proc = await asyncio.create_subprocess_exec(
            binary, "pull", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode == 0:
            return True, f"Pulled {image}"
        return False, stderr_b.decode(errors="replace").strip()
    except Exception as exc:
        return False, str(exc)


def build_volume_mounts(ws: Path) -> list[str]:
    mounts: list[str] = []

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


def apply_ee_kwargs(runner_kwargs: dict[str, Any], ws: Path) -> dict[str, Any]:
    """Inject EE container isolation kwargs into an ansible-runner call.

    When EE is disabled, returns the kwargs unchanged.
    """
    if not is_ee_enabled():
        return runner_kwargs

    runner_kwargs["process_isolation"] = True
    runner_kwargs["process_isolation_executable"] = get_container_runtime()
    runner_kwargs["container_image"] = get_ee_image()
    runner_kwargs["container_volume_mounts"] = build_volume_mounts(ws)

    envvars = runner_kwargs.get("envvars", {})
    envvars.pop("PYTHONHOME", None)
    envvars.pop("PYTHONPATH", None)
    envvars.pop("ANSIBLE_PYTHON_INTERPRETER", None)
    runner_kwargs["envvars"] = envvars

    return runner_kwargs


async def ee_exec(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    ws: Path | None = None,
) -> tuple[int, str, str]:
    """Execute a command inside the EE container.

    When EE is disabled, runs the command directly on the host.
    """
    if not is_ee_enabled():
        import os
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

    binary = _runtime_binary()
    if not binary:
        return 1, "", f"{get_container_runtime()} not found on PATH"

    container_cmd: list[str] = [binary, "run", "--rm"]

    mount_ws = ws or cwd
    if mount_ws:
        for mount in build_volume_mounts(mount_ws):
            container_cmd.extend(["-v", mount])
    if cwd:
        container_cmd.extend(["-w", str(cwd)])

    if env:
        for key, val in env.items():
            container_cmd.extend(["-e", f"{key}={val}"])

    _passthrough_vars = (
        "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
        "AWS_DEFAULT_REGION", "AWS_REGION", "AWS_PROFILE",
        "ARM_CLIENT_ID", "ARM_CLIENT_SECRET", "ARM_TENANT_ID", "ARM_SUBSCRIPTION_ID",
        "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_CLOUD_PROJECT",
        "TF_VAR_", "ANSIBLE_", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE",
        "HCLOUD_TOKEN", "DIGITALOCEAN_TOKEN", "DO_API_TOKEN",
    )
    import os
    for key, val in os.environ.items():
        if any(key.startswith(p) or key == p for p in _passthrough_vars) and (not env or key not in env):
            container_cmd.extend(["-e", f"{key}={val}"])

    container_cmd.append(get_ee_image())
    container_cmd.extend(cmd)

    logger.debug("ee_exec", cmd=container_cmd)

    proc = await asyncio.create_subprocess_exec(
        *container_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
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
