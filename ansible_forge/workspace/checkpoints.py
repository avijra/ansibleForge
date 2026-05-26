"""Git-based checkpoint system for agent file operations.

Uses a shadow git repo inside ``.tuyere/checkpoints/`` to track every
file-writing action the agent takes.  Users can list checkpoints and
revert the workspace to any prior state.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import Any

from ansible_forge.logging import get_logger

logger = get_logger(__name__)

_FILE_WRITING_TOOLS = frozenset({
    "generate_playbook", "write_file", "scaffold_role", "render_template",
    "generate_terraform", "manage_inventory", "import_project",
})

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Tuyere Agent",
    "GIT_AUTHOR_EMAIL": "agent@tuyere.ai",
    "GIT_COMMITTER_NAME": "Tuyere Agent",
    "GIT_COMMITTER_EMAIL": "agent@tuyere.ai",
}


def is_file_writing_tool(tool_name: str) -> bool:
    return tool_name in _FILE_WRITING_TOOLS


def _run_git(workspace: Path, *args: str, timeout: float = 10) -> subprocess.CompletedProcess[str]:
    import os
    env = {**os.environ, **_GIT_ENV}
    return subprocess.run(
        ["git", *args],
        cwd=workspace,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _ensure_repo(workspace: Path) -> bool:
    git_dir = workspace / ".git"
    if git_dir.is_dir():
        return True
    result = _run_git(workspace, "init", "-b", "main")
    if result.returncode != 0:
        logger.warning("checkpoint_git_init_failed", error=result.stderr.strip())
        return False
    _ensure_gitignore(workspace)
    _run_git(workspace, "add", "-A")
    _run_git(workspace, "commit", "-m", "Initial checkpoint", "--allow-empty")
    logger.info("checkpoint_repo_initialized", path=str(workspace))
    return True


def _ensure_gitignore(workspace: Path) -> None:
    gitignore = workspace / ".gitignore"
    entries_needed = {".tuyere/"}
    existing = set()
    if gitignore.exists():
        existing = set(gitignore.read_text().splitlines())
    missing = entries_needed - existing
    if missing:
        with gitignore.open("a") as f:
            for entry in missing:
                f.write(f"\n{entry}")


async def create_checkpoint(workspace: Path, label: str, step: int = 0) -> str | None:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _create_checkpoint_sync, workspace, label, step)
    except asyncio.CancelledError:
        logger.debug("checkpoint_cancelled", label=label, step=step)
        raise


def _create_checkpoint_sync(workspace: Path, label: str, step: int = 0) -> str | None:
    if not _ensure_repo(workspace):
        return None

    status = _run_git(workspace, "status", "--porcelain")
    if not status.stdout.strip():
        return None

    _run_git(workspace, "add", "-A")
    msg = f"checkpoint (step {step}): {label}"
    result = _run_git(workspace, "commit", "-m", msg)
    if result.returncode != 0:
        logger.debug("checkpoint_commit_failed", error=result.stderr.strip())
        return None

    sha = _run_git(workspace, "rev-parse", "--short", "HEAD")
    commit_hash = sha.stdout.strip()
    logger.info("checkpoint_created", hash=commit_hash, label=label, step=step)
    return commit_hash


def list_checkpoints(workspace: Path, limit: int = 50) -> list[dict[str, Any]]:
    if not (workspace / ".git").is_dir():
        return []

    result = _run_git(
        workspace, "log",
        f"--max-count={limit}",
        "--format=%H|%h|%s|%ct",
        "--reverse",
    )
    if result.returncode != 0:
        return []

    checkpoints: list[dict[str, Any]] = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) < 4:
            continue
        full_hash, short_hash, subject, timestamp = parts
        checkpoints.append({
            "hash": full_hash,
            "short_hash": short_hash,
            "label": subject,
            "timestamp": int(timestamp),
        })
    return checkpoints


async def revert_to_checkpoint(workspace: Path, commit_hash: str) -> dict[str, Any]:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, _revert_sync, workspace, commit_hash)
    except asyncio.CancelledError:
        logger.debug("checkpoint_revert_cancelled", hash=commit_hash)
        raise


def _revert_sync(workspace: Path, commit_hash: str) -> dict[str, Any]:
    if not (workspace / ".git").is_dir():
        return {"success": False, "error": "No checkpoint history exists"}

    verify = _run_git(workspace, "cat-file", "-t", commit_hash)
    if verify.returncode != 0 or verify.stdout.strip() != "commit":
        return {"success": False, "error": f"Invalid checkpoint: {commit_hash}"}

    diff_before = _run_git(workspace, "diff", "--stat", commit_hash)
    result = _run_git(workspace, "checkout", commit_hash, "--", ".")
    if result.returncode != 0:
        return {"success": False, "error": result.stderr.strip()}

    _run_git(workspace, "add", "-A")
    _run_git(workspace, "commit", "-m", f"Reverted to checkpoint {commit_hash[:8]}", "--allow-empty")

    files_changed = len(diff_before.stdout.strip().splitlines()) - 1 if diff_before.stdout.strip() else 0
    logger.info("checkpoint_reverted", target=commit_hash, files_changed=files_changed)
    return {
        "success": True,
        "reverted_to": commit_hash,
        "files_changed": max(files_changed, 0),
    }


def get_checkpoint_diff(workspace: Path, commit_hash: str) -> str:
    if not (workspace / ".git").is_dir():
        return ""
    result = _run_git(workspace, "diff", f"{commit_hash}^..{commit_hash}", "--stat")
    return result.stdout if result.returncode == 0 else ""
