"""Playbook retrieval endpoints for viewing generated playbooks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.workspace.project_layout import list_playbooks
from ansible_forge.workspace.resolver import resolve_workspace

router = APIRouter()


@router.get("/playbooks/{session_id}")
async def get_playbooks(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    """List and retrieve generated playbooks for a session."""
    ws = resolve_workspace(session_id)
    if ws is None:
        raise HTTPException(status_code=404, detail="Session workspace not found")

    playbook_names = list_playbooks(ws.path)
    playbooks: dict[str, str] = {}
    for name in playbook_names:
        path = ws.project_dir / name
        playbooks[name] = path.read_text(encoding="utf-8")

    return {
        "session_id": session_id,
        "playbook_count": len(playbooks),
        "playbooks": playbooks,
    }
