"""Execution Environment (EE) runtime helpers.

Centralises all container-based execution logic so that the rest of the
codebase only needs to call ``is_ee_enabled()``, ``apply_ee_kwargs()``,
or ``ee_exec()`` without knowing Docker/Podman specifics.
"""

from __future__ import annotations

import asyncio
import functools
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


_SUPPORTED_CONTAINER_ENGINES = frozenset({"docker", "podman"})


def normalize_container_runtime(runtime: str | None = None) -> str:
    """Normalize runtime strings to canonical engine names when possible."""
    configured = (runtime or get_container_runtime() or "").strip()
    if not configured:
        return "docker"
    leaf = Path(configured).name.lower()
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf in _SUPPORTED_CONTAINER_ENGINES:
        return leaf
    return configured


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
    configured = (runtime or get_container_runtime() or "").strip()
    if not configured:
        configured = "docker"

    candidates: list[str] = [configured]
    normalized = normalize_container_runtime(configured)
    if normalized not in candidates:
        candidates.append(normalized)

    for name in candidates:
        found = shutil.which(name)
        if found:
            return found

        direct = Path(name).expanduser()
        if direct.is_file() and os.access(direct, os.X_OK):
            return str(direct)

        if "/" in name or "\\" in name:
            continue
        for directory in _container_runtime_search_paths():
            candidate = Path(directory) / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    return None


def _runtime_binary() -> str | None:
    return resolve_container_runtime_binary()


_ARCH_ALIASES = {
    "arm64": "arm64/aarch64",
    "aarch64": "arm64/aarch64",
    "amd64": "amd64/x86_64",
    "x86_64": "amd64/x86_64",
    "arm": "arm/armv7",
    "ppc64le": "ppc64le",
    "s390x": "s390x",
}

_ee_platform_cache: dict[str, str] | None = None
_ee_platform_image: str | None = None


def _inspect_image_platform() -> dict[str, str] | None:
    binary = _runtime_binary()
    image = get_ee_image()
    if not binary or not image:
        return None
    env = os.environ.copy()
    env.update(_docker_host_env())
    import subprocess

    try:
        proc = subprocess.run(
            [binary, "image", "inspect", image, "--format", "{{.Os}}/{{.Architecture}}"],
            capture_output=True,
            text=True,
            timeout=15,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip().splitlines()[0].strip() if proc.stdout.strip() else ""
    if "/" not in raw:
        return None
    os_name, _, arch = raw.partition("/")
    os_name = os_name.strip().lower()
    arch = arch.strip().lower()
    if not os_name or not arch:
        return None
    return {"os": os_name, "arch": arch, "raw": f"{os_name}/{arch}"}


def detect_ee_platform(force: bool = False) -> dict[str, str] | None:
    """Return the EE container platform as {"os", "arch", "raw"} or None.

    Detected by inspecting the configured EE image with the container runtime.
    Cached per image so repeated calls are cheap. Returns None when EE is
    disabled or the platform cannot be determined.
    """
    global _ee_platform_cache, _ee_platform_image
    if not is_ee_enabled():
        return None
    image = get_ee_image()
    if not force and _ee_platform_cache is not None and _ee_platform_image == image:
        return _ee_platform_cache
    result = _inspect_image_platform()
    if result is not None:
        _ee_platform_cache = result
        _ee_platform_image = image
    return result


def get_ee_arch() -> str | None:
    platform = detect_ee_platform()
    return platform.get("arch") if platform else None


def ee_arch_alias() -> str | None:
    """Human-friendly architecture aliases (e.g. 'arm64/aarch64')."""
    arch = get_ee_arch()
    if not arch:
        return None
    return _ARCH_ALIASES.get(arch, arch)


def ee_platform_prompt_block() -> str:
    """System-prompt guidance describing the EE target platform.

    Returns an empty string when EE is disabled so the host-execution path is
    unaffected. The block tells the agent to select OS/architecture-matched
    binaries for ANY tool download (Terraform/OpenTofu, kubectl, helm, cloud
    CLIs, installers, etc.) — this is infrastructure-agnostic.
    """
    if not is_ee_enabled():
        return ""

    platform = detect_ee_platform()
    runtime = normalize_container_runtime()
    image = get_ee_image()

    if platform:
        arch = platform["arch"]
        alias = _ARCH_ALIASES.get(arch, arch)
        os_name = platform["os"]
        target = f"{os_name}/{arch} (CPU architecture: {alias})"
    else:
        os_name = "linux"
        arch = "the container's CPU architecture"
        alias = arch
        target = "linux/<container CPU architecture>"

    return (
        "## Execution Environment (ACTIVE)\n"
        "All commands, playbooks, and tools run INSIDE an isolated "
        f"{os_name} container ({runtime} image `{image}`), NOT on the host. "
        f"The container platform is **{target}**.\n\n"
        "CRITICAL — architecture-matched artifacts:\n"
        f"- When a task downloads a binary, release archive, or installer "
        f"(e.g. terraform/opentofu, kubectl, helm, oc, vault, consul, cloud "
        f"CLIs, language toolchains), you MUST select the **{os_name}** build "
        f"for **{alias}**. Never download macOS/Windows builds or a mismatched "
        "CPU architecture — they will fail with 'exec format error' or a "
        "runtime panic.\n"
        "- Do NOT assume the host's OS or CPU. Resolve the correct download URL "
        "using the EE platform above. When unsure of the running architecture, "
        "gather it first (e.g. ansible.builtin.setup → ansible_facts.architecture, "
        "or `uname -m`) and template the URL from it.\n"
        "- `sudo`/`become: true` is available in the EE; the runner user has "
        "passwordless sudo.\n"
    )


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
_EE_EXEC_STRIPPED_ENV_KEYS = _EE_STRIPPED_ENV_KEYS | frozenset(
    {
        "PATH",
        "PWD",
        "SHLVL",
        "_",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONEXECUTABLE",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
        "ANSIBLE_PYTHON_INTERPRETER",
        # Host dynamic-linker / loader paths break ELF resolution in the container
        "LD_LIBRARY_PATH",
        "LD_PRELOAD",
        "DYLD_LIBRARY_PATH",
        "DYLD_FALLBACK_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",
        # Host Ansible config/search paths do not exist inside the EE image
        "ANSIBLE_CONFIG",
        "ANSIBLE_COLLECTIONS_PATH",
        "ANSIBLE_COLLECTIONS_PATHS",
        "ANSIBLE_ROLES_PATH",
        "ANSIBLE_LIBRARY",
        "ANSIBLE_INVENTORY",
        "ANSIBLE_HOME",
        # Host TLS cert directory (file handled separately by cert-drop logic)
        "SSL_CERT_DIR",
    }
)


def _effective_ws_path(ws: Path, remote_ws: str | None) -> Path:
    return Path(remote_ws) if remote_ws else ws


def ensure_ee_workspace_dirs(ws: Path) -> None:
    for rel in (
        ".tuyere/ee-home/.ansible/tmp",
        ".tuyere/tmp/ansible",
        ".ansible/collections",
    ):
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
    # In remote mode the run dir is rsync'd to the remote host; an absolute
    # symlink would dangle there, so copy the inventory in instead.
    if is_remote_mode():
        shutil.copy2(inventory_path.resolve(), dest)
    else:
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


def _sanitize_ee_exec_env(env: dict[str, str] | None) -> dict[str, str]:
    if not env:
        return {}
    sanitized: dict[str, str] = {}
    for key, value in env.items():
        if key in _EE_EXEC_STRIPPED_ENV_KEYS:
            continue
        if key.startswith("LC_") or key in ("LANG", "LANGUAGE"):
            continue
        sanitized[key] = value
    return sanitized


_CERT_PATH_ENV_KEYS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")


def _drop_unmounted_cert_env(
    container_env: dict[str, str], mounts: list[str],
) -> None:
    """Remove CA-bundle env vars whose host path is not visible in the container.

    In frozen builds SSL_CERT_FILE points inside the app bundle, which is never
    mounted into the EE — passing it through breaks all HTTPS inside the
    container. Custom CA bundles under a mounted directory are kept.
    """
    roots = [m.split(":")[1] if m.count(":") >= 2 else m for m in mounts]
    for key in _CERT_PATH_ENV_KEYS:
        val = container_env.get(key)
        if not val:
            continue
        visible = any(val == root or val.startswith(root.rstrip("/") + "/") for root in roots)
        if not visible:
            container_env.pop(key, None)


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
    runtime_name = normalize_container_runtime()
    runner_kwargs["process_isolation"] = True
    runner_kwargs["process_isolation_executable"] = runtime_name
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

    extravars = runner_kwargs.get("extravars")
    if isinstance(extravars, dict):
        interp = str(extravars.get("ansible_python_interpreter", ""))
        if interp and not interp.startswith("/usr/"):
            extravars.pop("ansible_python_interpreter", None)
        if ctx.remote_workspace:
            _translate_local_paths_for_remote(extravars, ctx)

    return runner_kwargs


def _translate_local_paths_for_remote(extravars: dict[str, Any], ctx: EEContext) -> None:
    """Rewrite extravar values that are local workspace paths to their remote
    equivalents so file references (e.g. materialized SSH keys) resolve inside
    the container running on the remote Docker host."""
    ws_str = str(ctx.workspace)
    for key, value in list(extravars.items()):
        if not isinstance(value, str) or not value.startswith(ws_str):
            continue
        try:
            relative = Path(value).resolve().relative_to(ctx.workspace)
        except ValueError:
            continue
        extravars[key] = str(Path(ctx.effective_root) / relative)


async def _verify_ee_runner_execution(verify_ws: Path) -> tuple[bool, str]:
    import ansible_runner

    from ansible_forge.tools._runner_diagnostics import (
        diagnose_runner_failure,
        read_runner_stdout,
    )

    inventory_dir = verify_ws / "inventory"
    inventory_dir.mkdir(parents=True, exist_ok=True)
    inventory_path = inventory_dir / "hosts.yml"
    inventory_path.write_text(
        "all:\n  hosts:\n    localhost:\n      ansible_connection: local\n",
        encoding="utf-8",
    )

    run_dir = verify_ws / ".tuyere" / "runs" / "verify-runner"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "env").mkdir(exist_ok=True)

    runner_kwargs: dict[str, Any] = {
        "private_data_dir": str(run_dir),
        "project_dir": str(verify_ws),
        "module": "ansible.builtin.ping",
        "host_pattern": "localhost",
        "inventory": str(inventory_path),
        "envvars": {},
    }
    await configure_ee_runner(
        verify_ws,
        run_dir,
        runner_kwargs,
        inventory_path=inventory_path,
    )

    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                functools.partial(ansible_runner.run, **runner_kwargs),
            ),
            timeout=120,
        )
    except TimeoutError:
        return False, "EE ansible-runner check timed out after 120s"

    raw_stdout = read_runner_stdout(result)
    status = str(getattr(result, "status", "") or "")
    rc = getattr(result, "rc", None)
    if status == "successful" and rc in (None, 0):
        return True, "ansible-runner check OK"

    lowered = raw_stdout.lower()
    if "--die-with-parent" in lowered and "unknown flag" in lowered:
        return (
            False,
            "EE ansible-runner path is misconfigured (docker invoked with bwrap flags)",
        )

    diag = diagnose_runner_failure([], raw_stdout=raw_stdout, rc=rc)
    return False, f"EE ansible-runner check failed: {diag}"


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
    try:
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

        runner_ok, runner_detail = await _verify_ee_runner_execution(verify_ws)
        if not runner_ok:
            return False, runner_detail

        version_line = combined.splitlines()[0] if combined else "ansible available"
        return True, version_line
    finally:
        shutil.rmtree(verify_ws, ignore_errors=True)


async def test_remote_connection() -> tuple[bool, str]:
    remote_host = effective_ee_remote_host()
    if not remote_host:
        return False, "Remote host is not configured"

    from ansible_forge.tools.workspace_sync import normalize_ssh_host

    host = normalize_ssh_host(remote_host)
    runtime_name = normalize_container_runtime()
    proc = await asyncio.create_subprocess_exec(
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        host,
        f"{runtime_name} info --format '{{.ServerVersion}}'",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=20)
    if proc.returncode != 0:
        detail = stderr_b.decode(errors="replace").strip() or "SSH or container runtime check failed"
        return False, detail
    version = stdout_b.decode(errors="replace").strip()
    return True, f"Connected to {host} ({runtime_name} {version or 'available'})"


async def ee_exec(
    cmd: list[str],
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    ws: Path | None = None,
    extra_run_args: list[str] | None = None,
) -> tuple[int, str, str]:
    """Execute a command inside the EE container.

    ``extra_run_args`` are inserted verbatim into the ``run`` argument list
    (e.g. an extra ``-v`` mount). Ignored when EE is disabled.
    """
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
            mount_ws = Path.cwd()
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

    runtime_name = normalize_container_runtime()
    if runtime_name == "docker":
        container_cmd.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    if extra_run_args:
        container_cmd.extend(extra_run_args)

    mounts: list[str] = []
    if mount_ws:
        mounts = build_volume_mounts(Path(mount_ws), remote_ws=remote_ws)
        for mount in mounts:
            container_cmd.extend(["-v", mount])
    if effective_cwd:
        container_cmd.extend(["-w", str(effective_cwd)])

    container_env: dict[str, str] = {}
    if mount_ws:
        ensure_ee_workspace_dirs(Path(mount_ws))
        container_env.update(ee_bootstrap_env(Path(mount_ws), remote_ws))
    container_env.update(_ee_locale_env())
    if env:
        container_env.update(_sanitize_ee_exec_env(env))

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
        "SSL_CERT_FILE",
        "REQUESTS_CA_BUNDLE",
        "HCLOUD_TOKEN",
        "DIGITALOCEAN_TOKEN",
        "DO_API_TOKEN",
    )
    for key, val in os.environ.items():
        if key in container_env or key in _EE_EXEC_STRIPPED_ENV_KEYS:
            continue
        if any(key.startswith(p) or key == p for p in _passthrough_vars):
            container_env[key] = val

    _drop_unmounted_cert_env(container_env, mounts)

    for key, val in container_env.items():
        container_cmd.extend(["-e", f"{key}={val}"])

    container_cmd.append(get_ee_image())
    container_cmd.extend(cmd)

    logger.debug("ee_exec", cmd=container_cmd)

    proc = await asyncio.create_subprocess_exec(
        *container_cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_merged_subprocess_env(),
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


async def build_interactive_shell_argv(
    ws: Path,
) -> tuple[list[str], dict[str, str]]:
    """Build argv + env for an interactive shell inside the EE container.

    Used by the terminal endpoint so the user's shell runs in the same
    environment as agent execution. In remote mode the workspace is synced and
    the container runs on the remote Docker host via ``DOCKER_HOST``.
    """
    binary = _runtime_binary()
    if not binary:
        raise RuntimeError(f"{get_container_runtime()} not found on PATH")

    remote_ws: str | None = None
    if is_remote_mode():
        if not effective_ee_remote_host():
            raise RuntimeError("Remote host is not configured")
        remote_ws = await sync_to_remote(ws)

    ensure_ee_workspace_dirs(ws)
    workdir = _effective_ws_path(ws, remote_ws)

    argv: list[str] = [binary, "run", "--rm", "-i", "-t"]
    if normalize_container_runtime() == "docker" and not is_remote_mode():
        argv.extend(["--user", f"{os.getuid()}:{os.getgid()}"])

    for mount in build_volume_mounts(ws, remote_ws=remote_ws):
        argv.extend(["-v", mount])
    argv.extend(["-w", str(workdir)])

    container_env: dict[str, str] = {}
    container_env.update(ee_bootstrap_env(ws, remote_ws))
    container_env.update(_ee_locale_env())
    container_env["TERM"] = "xterm-256color"
    for key, val in container_env.items():
        argv.extend(["-e", f"{key}={val}"])

    argv.append(get_ee_image())
    argv.extend(["/bin/bash"])

    return argv, _merged_subprocess_env()
