"""Workspace file browser and editor endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.resolver import resolve_workspace

router = APIRouter()

_TEXT_SUFFIXES = frozenset({
    ".yml", ".yaml", ".j2", ".cfg", ".ini", ".conf", ".txt",
    ".json", ".sh", ".bash", ".py", ".md", ".toml",
    ".tf", ".tfvars", ".hcl", ".tfstate",
    ".xml", ".csv", ".env", ".properties",
    ".sql", ".dockerfile", ".gitignore",
})
_TEXT_NAMES = frozenset({
    "hosts", "extravars", "ansible.cfg",
    "Makefile", "Dockerfile", "Vagrantfile", "Jenkinsfile",
    "Gemfile", "Rakefile", "Procfile",
    ".gitignore", ".dockerignore", ".editorconfig",
})
_SKIP_DIRS = frozenset({"__pycache__", ".git", ".tuyere", ".terraform", "node_modules"})
_MAX_FILE_SIZE = 512_000


def _collect_files(base: Path, root: Path) -> list[dict[str, Any]]:
    """Walk the workspace tree and collect text files with relative paths."""
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        return entries

    for item in sorted(root.rglob("*")):
        if not item.is_file():
            continue
        if any(part in _SKIP_DIRS for part in item.parts):
            continue
        if item.suffix not in _TEXT_SUFFIXES and item.name not in _TEXT_NAMES:
            continue
        if item.stat().st_size > _MAX_FILE_SIZE:
            continue

        rel = str(item.relative_to(base))
        try:
            content = item.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        entries.append({
            "path": rel,
            "name": item.name,
            "size": len(content),
            "content": content,
        })

    return entries


@router.get("/workspace/{session_id}/files")
async def get_workspace_files(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    """Return all text files in the session workspace."""
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    files = _collect_files(ws.path, ws.path)

    return {
        "session_id": session_id,
        "file_count": len(files),
        "files": files,
    }


class FileSaveRequest(BaseModel):
    path: str = Field(..., description="Relative path inside the workspace")
    content: str = Field(..., description="New file content")


@router.put("/workspace/{session_id}/files")
async def save_workspace_file(
    session_id: str,
    body: FileSaveRequest,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    """Write content to a file inside the session workspace."""
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    target = (ws.path / body.path).resolve()
    if not str(target).startswith(str(ws.path.resolve())):
        raise HTTPException(status_code=400, detail="Path traversal not allowed")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.content, encoding="utf-8")

    return {"path": body.path, "size": len(body.content), "ok": True}


@router.get("/workspace/{session_id}/search")
async def search_workspace(
    session_id: str,
    q: str = "",
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    from ansible_forge.workspace.context import search_workspace_files

    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    results = search_workspace_files(ws.path, query=q, limit=20)
    return {"session_id": session_id, "results": results}
