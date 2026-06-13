"""Container-native Ansible execution for remote Execution Environments.

In remote EE mode ansible-runner's ``process_isolation`` cannot be used: it
writes its private_data_dir on the local filesystem while the container runs on
a remote Docker host, so prep files never reach the container. Instead we run
``ansible-playbook`` / ``ansible`` directly inside the container via ``ee_exec``
(which syncs the workspace to the remote host first), capture the JSON stdout
callback output, and wrap it in a result shim that the existing parsers
understand.
"""

from __future__ import annotations

import io
import json
import re
import uuid
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_JSON_MARKER = '"plays"'


class ContainerRunResult:
    """Minimal ansible-runner-compatible result built from captured stdout."""

    def __init__(self, rc: int, stdout_text: str) -> None:
        self.rc = rc
        self.stdout = io.StringIO(stdout_text)
        self.events: list[dict[str, Any]] = []
        self.status = "successful" if rc == 0 else "failed"
        self.stats = _extract_stats(stdout_text)


def _extract_stats(stdout_text: str) -> dict[str, Any]:
    if _JSON_MARKER not in stdout_text:
        return {}
    cleaned = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", stdout_text)
    try:
        data = json.loads(cleaned)
    except (ValueError, TypeError):
        idx = cleaned.find("\n{")
        if idx < 0:
            return {}
        try:
            data = json.loads(cleaned[idx + 1:])
        except (ValueError, TypeError):
            return {}
    stats = data.get("stats") if isinstance(data, dict) else None
    return stats if isinstance(stats, dict) else {}


def _compose_stdout(out: str, err: str) -> str:
    """Keep clean JSON when present; otherwise include stderr for diagnosis."""
    if _JSON_MARKER in out:
        return out
    if err.strip():
        return (out + "\n" + err).strip()
    return out


async def _run_in_container(
    argv: list[str],
    ws: Path,
    envvars: dict[str, str],
    timeout: int,
) -> ContainerRunResult:
    from ansible_forge.tools.ee_runtime import ee_exec, is_remote_mode
    from ansible_forge.tools.workspace_sync import sync_from_remote

    env = {
        "ANSIBLE_STDOUT_CALLBACK": "json",
        "ANSIBLE_FORCE_COLOR": "0",
        "ANSIBLE_NOCOLOR": "1",
        "ANSIBLE_HOST_KEY_CHECKING": "False",
        **envvars,
    }
    rc, out, err = await ee_exec(argv, cwd=ws, env=env, ws=ws, timeout=timeout)

    if is_remote_mode():
        try:
            await sync_from_remote(ws)
        except Exception as exc:
            logger.warning("sync_from_remote_failed", error=str(exc))

    return ContainerRunResult(rc, _compose_stdout(out, err))


def _translate_paths(extravars: dict[str, Any], ws: Path) -> dict[str, Any]:
    """Rewrite local workspace file paths to their container-mounted location.

    In remote mode the workspace is mounted at the remote root inside the
    container, so absolute local paths (e.g. materialized SSH keys) must be
    remapped. In local mode the mount path equals the local path, so values are
    returned unchanged.
    """
    from ansible_forge.tools.ee_runtime import is_remote_mode

    if not is_remote_mode():
        return extravars

    from ansible_forge.tools.workspace_sync import remote_workspace_path

    remote_root = remote_workspace_path(ws.resolve())
    ws_str = str(ws.resolve())
    translated: dict[str, Any] = {}
    for key, value in extravars.items():
        if isinstance(value, str) and value.startswith(ws_str):
            try:
                relative = Path(value).resolve().relative_to(ws.resolve())
                translated[key] = f"{remote_root}/{relative}"
                continue
            except ValueError:
                pass
        translated[key] = value
    return translated


def _write_extravars(ws: Path, extravars: dict[str, Any]) -> Path | None:
    if not extravars:
        return None
    tmp_dir = ws / ".tuyere" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    ev_file = tmp_dir / f"extravars-{uuid.uuid4().hex[:12]}.json"
    ev_file.write_text(json.dumps(_translate_paths(extravars, ws)), encoding="utf-8")
    return ev_file


async def run_playbook_in_container(
    *,
    ws: Path,
    playbook: str,
    inventory: str = "",
    cmdline_args: list[str] | None = None,
    extravars: dict[str, Any] | None = None,
    envvars: dict[str, str] | None = None,
    verbosity: int = 0,
    timeout: int = 1800,
) -> ContainerRunResult:
    """Run a playbook inside the EE container and return a runner-like result."""
    argv = ["ansible-playbook", playbook]
    if inventory:
        argv.extend(["-i", inventory])
    if verbosity and verbosity > 0:
        argv.append("-" + "v" * min(verbosity, 4))
    if cmdline_args:
        argv.extend(cmdline_args)

    ev_file = _write_extravars(ws, extravars or {})
    if ev_file is not None:
        argv.extend(["-e", f"@{ev_file.relative_to(ws)}"])

    try:
        return await _run_in_container(argv, ws, envvars or {}, timeout)
    finally:
        if ev_file is not None:
            ev_file.unlink(missing_ok=True)
