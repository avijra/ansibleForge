"""Checkpoint management API — list and revert workspace checkpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.checkpoints import (
    get_checkpoint_diff,
    list_checkpoints,
    revert_to_checkpoint,
)
from ansible_forge.workspace.resolver import resolve_workspace

router = APIRouter()


@router.get("/checkpoints/{session_id}")
async def get_checkpoints(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    items = list_checkpoints(ws.path)
    return {"session_id": session_id, "checkpoints": items}


@router.post("/checkpoints/{session_id}/revert")
async def revert_checkpoint(
    session_id: str,
    body: dict[str, str],
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    commit_hash = body.get("hash", "")
    if not commit_hash:
        raise HTTPException(status_code=422, detail="Missing 'hash' in request body")

    result = await revert_to_checkpoint(ws.path, commit_hash)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Revert failed"))

    return {"session_id": session_id, **result}


@router.get("/checkpoints/{session_id}/{commit_hash}/diff")
async def checkpoint_diff(
    session_id: str,
    commit_hash: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, str]:
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    diff = get_checkpoint_diff(ws.path, commit_hash)
    return {"session_id": session_id, "hash": commit_hash, "diff": diff}
