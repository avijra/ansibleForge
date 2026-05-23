"""Session persistence endpoints for listing and replaying conversations."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.persistence.session_store import SessionStore

router = APIRouter()

def _get_store() -> SessionStore:
    return SessionStore.get_instance()


@router.get("/sessions")
async def list_sessions(
    limit: int = 50,
    project_path: str | None = None,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    if project_path:
        return {"sessions": await store.alist_by_project_path(project_path)}
    return {"sessions": await store.alist_sessions(limit=limit)}


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    events = await store.aget_events(session_id)
    return {"session_id": session_id, "events": events}


@router.post("/sessions/{session_id}/reset")
async def reset_session(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    if not await store.areset_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found")

    from ansible_forge.agent.event_bus import EventBusRegistry
    from ansible_forge.api.endpoints.chat import _active_tasks, get_orchestrator

    active_task = _active_tasks.get(session_id)
    if active_task and not active_task.done():
        active_task.cancel()

    orch = get_orchestrator()
    orch.reset_session(session_id)

    bus = EventBusRegistry.get_instance().get(session_id)
    if bus is not None:
        bus.mark_done(bus._run_gen)

    return {"session_id": session_id, "status": "reset"}


@router.get("/sessions/{session_id}/usage")
async def get_session_usage(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    from ansible_forge.api.endpoints.chat import get_orchestrator

    orch = get_orchestrator()
    state = orch._sessions.get(session_id)
    if not state:
        return {
            "session_id": session_id,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
        }
    return {
        "session_id": session_id,
        "prompt_tokens": state._total_prompt_tokens,
        "completion_tokens": state._total_completion_tokens,
        "total_tokens": state._total_prompt_tokens + state._total_completion_tokens,
        "estimated_cost": round(state._total_cost, 6),
    }


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    store = _get_store()
    deleted = await store.adelete_session(session_id)

    from ansible_forge.agent.event_bus import EventBusRegistry
    from ansible_forge.api.endpoints.chat import _active_tasks, get_orchestrator

    active_task = _active_tasks.get(session_id)
    if active_task and not active_task.done():
        active_task.cancel()

    orch = get_orchestrator()
    orch.destroy_session(session_id)
    EventBusRegistry.get_instance().cleanup(session_id)

    return {"session_id": session_id, "deleted": deleted}
