"""Sync local workspaces to a remote Docker host for EE execution."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
from pathlib import Path

import structlog

from ansible_forge.config import effective_ee_remote_host, effective_ee_remote_workspace_root

logger = structlog.get_logger(__name__)

_sync_fingerprints: dict[str, str] = {}
_sync_locks: dict[str, asyncio.Lock] = {}


def _lock_for(cache_key: str) -> asyncio.Lock:
    lock = _sync_locks.get(cache_key)
    if lock is None:
        lock = asyncio.Lock()
        _sync_locks[cache_key] = lock
    return lock


def normalize_ssh_host(host: str) -> str:
    value = host.strip()
    if value.startswith("ssh://"):
        return value[len("ssh://") :]
    return value


def docker_host_url(host: str) -> str:
    value = host.strip()
    if value.startswith("ssh://"):
        return value
    return f"ssh://{value}"


def remote_workspace_path(local_ws: Path) -> str:
    root = effective_ee_remote_workspace_root().rstrip("/")
    digest = hashlib.sha256(str(local_ws.resolve()).encode()).hexdigest()[:16]
    name = local_ws.name.replace(" ", "_") or "workspace"
    return f"{root}/{name}-{digest}"


def local_to_remote_path(local_path: Path, local_ws: Path, remote_ws: str) -> Path:
    resolved_local = local_path.resolve()
    resolved_ws = local_ws.resolve()
    relative = resolved_local.relative_to(resolved_ws)
    return Path(remote_ws) / relative


def _workspace_fingerprint(ws: Path) -> str:
    digest = hashlib.sha256()
    root_stat = ws.stat()
    digest.update(str(root_stat.st_mtime_ns).encode())
    digest.update(str(root_stat.st_size).encode())
    count = 0
    truncated = False
    for path in sorted(ws.rglob("*")):
        if not path.is_file():
            continue
        stat = path.stat()
        digest.update(str(path.relative_to(ws)).encode())
        digest.update(str(stat.st_mtime_ns).encode())
        digest.update(str(stat.st_size).encode())
        count += 1
        if count >= 5000:
            truncated = True
            break
    if truncated:
        # Large workspaces can change beyond the cap without altering the
        # hashed prefix; salt with a random token so we never skip a sync.
        digest.update(os.urandom(8))
    return digest.hexdigest()[:16]


async def sync_to_remote(local_ws: Path, remote_host: str | None = None) -> str:
    host = normalize_ssh_host(remote_host or effective_ee_remote_host() or "")
    if not host:
        raise ValueError("Remote host is not configured")

    local_ws = local_ws.resolve()
    remote_path = remote_workspace_path(local_ws)
    cache_key = f"{host}:{local_ws}"

    # Serialize concurrent syncs of the same workspace so overlapping tool
    # calls don't run competing rsyncs against the same destination.
    async with _lock_for(cache_key):
        fingerprint = _workspace_fingerprint(local_ws)
        if _sync_fingerprints.get(cache_key) == fingerprint:
            logger.debug("workspace_sync_skipped", local=str(local_ws), remote=remote_path)
            return remote_path

        if shutil.which("rsync") is None:
            raise RuntimeError("rsync is required for remote EE execution but was not found on PATH")

        destination = f"{host}:{remote_path}/"
        proc = await asyncio.create_subprocess_exec(
            "rsync",
            "-az",
            "--delete",
            f"{local_ws}/",
            destination,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode != 0:
            # Never leave a stale fingerprint after a failed sync.
            _sync_fingerprints.pop(cache_key, None)
            detail = stderr_b.decode(errors="replace").strip() or stdout_b.decode(errors="replace").strip()
            raise RuntimeError(f"Workspace sync failed: {detail}")

        _sync_fingerprints[cache_key] = fingerprint
        logger.info("workspace_synced", local=str(local_ws), remote=remote_path)
        return remote_path


async def sync_from_remote(local_ws: Path, remote_host: str | None = None) -> None:
    """Pull files generated on the remote host back into the local workspace.

    Used after container-native remote execution so generated playbooks, logs,
    and artifacts appear locally. Does not delete local-only files.
    """
    host = normalize_ssh_host(remote_host or effective_ee_remote_host() or "")
    if not host:
        raise ValueError("Remote host is not configured")

    local_ws = local_ws.resolve()
    remote_path = remote_workspace_path(local_ws)
    cache_key = f"{host}:{local_ws}"

    if shutil.which("rsync") is None:
        raise RuntimeError("rsync is required for remote EE execution but was not found on PATH")

    async with _lock_for(cache_key):
        proc = await asyncio.create_subprocess_exec(
            "rsync",
            "-az",
            f"{host}:{remote_path}/",
            f"{local_ws}/",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=600)
        if proc.returncode != 0:
            detail = stderr_b.decode(errors="replace").strip() or stdout_b.decode(errors="replace").strip()
            raise RuntimeError(f"Workspace sync-back failed: {detail}")
        # Local tree changed; force a fresh push fingerprint on next sync_to_remote.
        _sync_fingerprints.pop(cache_key, None)
        logger.info("workspace_synced_back", local=str(local_ws), remote=remote_path)


def clear_sync_cache() -> None:
    _sync_fingerprints.clear()
