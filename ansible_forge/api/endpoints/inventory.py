"""Inventory management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.manager import WorkspaceManager

router = APIRouter()


@router.get("/inventory/{session_id}")
async def get_inventory(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    """Retrieve inventory files for a session."""
    ws_mgr = WorkspaceManager()
    ws = ws_mgr.get(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    inv_dir = ws.inventory_dir
    files: dict[str, str] = {}
    if inv_dir.exists():
        for f in inv_dir.iterdir():
            if f.is_file():
                files[f.name] = f.read_text(encoding="utf-8")

    return {
        "session_id": session_id,
        "inventory_files": files,
    }
