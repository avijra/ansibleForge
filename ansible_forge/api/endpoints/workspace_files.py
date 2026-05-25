"""Workspace file browser and editor endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.resolver import resolve_workspace

router = APIRouter()

_SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".tuyere", ".terraform", "node_modules",
    ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache",
})
_BINARY_SUFFIXES = frozenset({
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp3", ".mp4", ".wav", ".avi", ".mov", ".mkv",
    ".db", ".sqlite", ".sqlite3",
    ".o", ".a", ".class", ".jar",
    ".tfstate.backup",
})
_MAX_FILE_SIZE = 512_000


def _collect_files(base: Path, root: Path) -> list[dict[str, Any]]:
    """Walk the workspace tree and collect all text-readable files and visible directories."""
    entries: list[dict[str, Any]] = []
    if not root.is_dir():
        return entries

    seen_dirs: set[str] = set()
    for item in sorted(root.rglob("*")):
        if any(part in _SKIP_DIRS for part in item.relative_to(base).parts):
            continue

        if item.is_dir():
            rel = str(item.relative_to(base))
            if rel not in seen_dirs:
                seen_dirs.add(rel)
                entries.append({
                    "path": rel,
                    "name": item.name,
                    "size": 0,
                    "content": "",
                    "is_dir": True,
                })
            continue

        if not item.is_file():
            continue
        if item.suffix.lower() in _BINARY_SUFFIXES:
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
