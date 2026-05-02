"""Session persistence endpoints for listing and replaying conversations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.persistence.session_store import SessionStore

router = APIRouter()

_store: SessionStore | None = None


def _get_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store


@router.get("/sessions")
async def list_sessions(
    limit: int = 50,
    project_path: str | None = None,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    if project_path:
        return {"sessions": store.list_by_project_path(project_path)}
    return {"sessions": store.list_sessions(limit=limit)}


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    events = store.get_events(session_id)
    return {"session_id": session_id, "events": events}


@router.post("/sessions/{session_id}/reset")
async def reset_session(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    if not store.reset_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    from ansible_forge.api.endpoints.chat import get_orchestrator

    orch = get_orchestrator()
    orch.reset_session(session_id)

    return {"session_id": session_id, "status": "reset"}


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    deleted = store.delete_session(session_id)
    return {"session_id": session_id, "deleted": deleted}
