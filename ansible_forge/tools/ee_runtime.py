"""Execution Environment (EE) runtime helpers.

Centralises all container-based execution logic so that the rest of the
codebase only needs to call ``is_ee_enabled()``, ``apply_ee_kwargs()``,
or ``ee_exec()`` without knowing Docker/Podman specifics.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
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


def _container_runtime_search_paths() -> list[str]:
    paths: list[str] = []
    if sys.platform == "darwin":
        paths.extend(
            [
                "/usr/local/bin",
                "/opt/homebrew/bin",
                "/Applications/Docker.app/Contents/Resources/bin",
            ]
        )
    elif sys.platform == "linux":
        paths.extend(["/usr/local/bin", "/usr/bin", "/snap/bin"])
    return paths


def resolve_container_runtime_binary(runtime: str | None = None) -> str | None:
    name = runtime or get_container_runtime()
    found = shutil.which(name)
    if found:
        return found
    for directory in _container_runtime_search_paths():
        candidate = Path(directory) / name
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def _runtime_binary() -> str | None:
    return resolve_container_runtime_binary()


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


_EE_STRIPPED_ENV_KEYS = frozenset({"HOME", "TMPDIR", "USER", "LOGNAME"})


def _effective_ws_path(ws: Path, remote_ws: str | None) -> Path:
    return Path(remote_ws) if remote_ws else ws


def ensure_ee_workspace_dirs(ws: Path) -> None:
    for rel in (".tuyere/ee-home/.ansible/tmp", ".tuyere/tmp/ansible"):
        (ws / rel).mkdir(parents=True, exist_ok=True)


def ee_bootstrap_env(ws: Path, remote_ws: str | None = None) -> dict[str, str]:
    root = _effective_ws_path(ws, remote_ws)
    home = root / ".tuyere" / "ee-home"
    tmp = root / ".tuyere" / "tmp" / "ansible"
    return {
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "ANSIBLE_LOCAL_TMP": str(tmp),
        "ANSIBLE_REMOTE_TMP": str(tmp),
    }


@dataclass(frozen=True)
class EEContext:
    workspace: Path
    remote_workspace: str | None
    effective_root: Path


def build_ee_context(ws: Path, remote_ws: str | None = None) -> EEContext:
    effective_remote = remote_ws
    if is_remote_mode() and not effective_remote:
        from ansible_forge.tools.workspace_sync import remote_workspace_path

        effective_remote = remote_workspace_path(ws)
    root = _effective_ws_path(ws, effective_remote)
    return EEContext(workspace=ws.resolve(), remote_workspace=effective_remote, effective_root=root)


def stage_runner_inventory(run_dir: Path, inventory_path: Path) -> None:
    if not inventory_path.exists():
        return
    dest = run_dir / "inventory"
    if dest.is_symlink() or dest.exists() or dest.is_file():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink(missing_ok=True)
    dest.symlink_to(inventory_path.resolve())


def _inject_ee_ansible_paths(envvars: dict[str, str], ctx: EEContext) -> None:
    local_collections = ctx.workspace / ".ansible" / "collections"
    local_collections.mkdir(parents=True, exist_ok=True)
    collections = ctx.effective_root / ".ansible" / "collections"
    roles = ctx.effective_root / "roles"
    envvars["ANSIBLE_COLLECTIONS_PATH"] = (
        f"{collections}:/usr/share/ansible/collections"
    )
    envvars["ANSIBLE_ROLES_PATH"] = str(roles)


async def configure_ee_runner(
    ws: Path,
    run_dir: Path,
    runner_kwargs: dict[str, Any],
    *,
    inventory_path: Path | None = None,
) -> None:
    if not is_ee_enabled():
        return
    ensure_ee_workspace_dirs(ws)
    if inventory_path is not None:
        stage_runner_inventory(run_dir, inventory_path)
    remote_ws: str | None = None
    if is_remote_mode():
        remote_ws = await sync_to_remote(ws)
    apply_ee_kwargs(
        runner_kwargs,
        ws,
        remote_ws=remote_ws,
        run_dir=run_dir,
    )


def inject_ee_container_env(
    envvars: dict[str, str],
    ws: Path,
    remote_ws: str | None = None,
) -> dict[str, str]:
    ensure_ee_workspace_dirs(ws)
    for key in list(envvars):
        if key in _EE_STRIPPED_ENV_KEYS or (
            key.startswith("ANSIBLE_") and "TMP" in key
        ):
            envvars.pop(key, None)
    envvars.update(ee_bootstrap_env(ws, remote_ws))
    _inject_ee_ansible_paths(envvars, build_ee_context(ws, remote_ws))
    return sanitize_runner_envvars(envvars)


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
    binary = resolve_container_runtime_binary(rt)
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
    ensure_ee_workspace_dirs(ws)
    if not is_remote_mode():
        return None
    if not effective_ee_remote_host():
        raise RuntimeError("Remote host is not configured")
    return await sync_to_remote(ws)


def apply_ee_kwargs(
    runner_kwargs: dict[str, Any],
    ws: Path,
    remote_ws: str | None = None,
    run_dir: Path | None = None,
) -> dict[str, Any]:
    """Inject EE container isolation kwargs into an ansible-runner call."""
    if not is_ee_enabled():
        return runner_kwargs

    ctx = build_ee_context(ws, remote_ws)
    runtime_bin = resolve_container_runtime_binary()
    runner_kwargs["process_isolation"] = True
    runner_kwargs["process_isolation_executable"] = (
        runtime_bin or get_container_runtime()
    )
    runner_kwargs["container_image"] = get_ee_image()
    runner_kwargs["host_cwd"] = str(ctx.workspace)
    runner_kwargs["container_workdir"] = str(ctx.effective_root)
    runner_kwargs["container_volume_mounts"] = build_volume_mounts(
        ws,
        remote_ws=ctx.remote_workspace,
    )

    if run_dir is not None and ctx.remote_workspace:
        runner_kwargs["private_data_dir"] = str(
            local_to_remote_path(run_dir.resolve(), ctx.workspace, ctx.remote_workspace)
        )

    envvars = runner_kwargs.get("envvars", {})
    envvars.pop("PYTHONHOME", None)
    envvars.pop("PYTHONPATH", None)
    envvars.pop("ANSIBLE_PYTHON_INTERPRETER", None)
    envvars.update(_docker_host_env())
    inject_ee_container_env(envvars, ws, ctx.remote_workspace)
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

    import tempfile

    verify_ws = Path(tempfile.mkdtemp(prefix="tuyere-ee-verify-"))

    rc, stdout, stderr = await ee_exec(["ansible", "--version"], ws=verify_ws, timeout=60)
    combined = (stderr or stdout or "").strip()
    if rc != 0:
        detail = combined[:400] or f"ansible --version exited with code {rc}"
        if "locale" in detail.lower():
            return False, f"EE locale misconfigured: {detail}"
        if "permission denied" in detail.lower():
            return False, f"EE container HOME/tmp not writable: {detail}"
        return False, f"EE ansible check failed: {detail}"

    rc, stdout, stderr = await ee_exec(
        ["ansible", "localhost", "-m", "ping", "-c", "local", "-i", "localhost,"],
        ws=verify_ws,
        timeout=90,
    )
    ping_output = (stderr or stdout or "").strip()
    if rc != 0:
        detail = ping_output[:400] or f"ansible ping exited with code {rc}"
        if "permission denied" in detail.lower() or "/.ansible" in detail:
            return False, f"EE container HOME/tmp not writable: {detail}"
        return False, f"EE ansible ping check failed: {detail}"

    playbooks = verify_ws / "playbooks"
    playbooks.mkdir(exist_ok=True)
    (playbooks / "ping.yml").write_text(
        "---\n- hosts: localhost\n  connection: local\n  gather_facts: false\n"
        "  tasks:\n    - ansible.builtin.ping:\n",
        encoding="utf-8",
    )
    rc, stdout, stderr = await ee_exec(
        [
            "ansible-playbook",
            "playbooks/ping.yml",
            "-i",
            "localhost,",
        ],
        ws=verify_ws,
        timeout=90,
    )
    playbook_output = (stderr or stdout or "").strip()
    if rc != 0:
        detail = playbook_output[:400] or f"ansible-playbook exited with code {rc}"
        if "could not be found" in detail.lower():
            return False, f"EE playbook path contract broken: {detail}"
        return False, f"EE ansible-playbook check failed: {detail}"

    version_line = combined.splitlines()[0] if combined else "ansible available"
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

    if effective_cwd is None and mount_ws:
        effective_cwd = _effective_ws_path(Path(mount_ws), remote_ws)

    container_cmd: list[str] = [binary, "run", "--rm"]

    if get_container_runtime() == "docker":
        container_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    if mount_ws:
        for mount in build_volume_mounts(Path(mount_ws), remote_ws=remote_ws):
            container_cmd.extend(["-v", mount])
    if effective_cwd:
        container_cmd.extend(["-w", str(effective_cwd)])

    container_env: dict[str, str] = {}
    if mount_ws:
        ensure_ee_workspace_dirs(Path(mount_ws))
        container_env.update(ee_bootstrap_env(Path(mount_ws), remote_ws))
    container_env.update(_ee_locale_env())
    if env:
        container_env.update(env)

    for key, val in container_env.items():
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
        if key in container_env or key in _EE_STRIPPED_ENV_KEYS:
            continue
        if any(key.startswith(p) or key == p for p in _passthrough_vars):
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
