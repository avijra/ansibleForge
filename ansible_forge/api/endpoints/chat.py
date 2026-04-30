"""Main conversational chat endpoint with SSE streaming."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from ansible_forge.agent.orchestrator import Orchestrator
from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.api.schemas.requests import ApprovalRequest, ChatRequest
from ansible_forge.api.schemas.responses import (
    ApprovalResponse,
    ChatResponse,
    SessionStatusResponse,
)
from ansible_forge.logging import get_logger
from ansible_forge.persistence.session_store import SessionStore

logger = get_logger(__name__)

_session_store: SessionStore | None = None


def _get_session_store() -> SessionStore:
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store

router = APIRouter()

_orchestrator: Orchestrator | None = None


async def _run_reflection(session_id: str, orch: Orchestrator, store: SessionStore) -> None:
    try:
        from ansible_forge.knowledge.reflection import reflect_on_session

        events = store.get_events(session_id)
        count = await reflect_on_session(
            session_id, events, orch._llm, orch._experience_store
        )
        if count:
            logger.info("reflection_complete", session_id=session_id, learnings=count)
    except Exception:
        logger.debug("reflection_background_failed", session_id=session_id, exc_info=True)


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    _: Any = Depends(verify_api_key),
) -> EventSourceResponse | ChatResponse:
    """Send a natural-language message to the AnsibleForge agent.

    Returns an SSE stream of agent events (thinking, tool_call, tool_result,
    message, approval_required, etc.).
    """
    orch = get_orchestrator()
    session_id = request.session_id
    if session_id is None:
        state = orch.create_session()
        session_id = state.session_id

    store = _get_session_store()
    store.save_session(session_id, status="active")
    store.save_event(session_id, "user_message", {"content": request.message})

    async def event_stream():  # type: ignore[return]
        yield {
            "event": "session_started",
            "data": json.dumps({"session_id": session_id}),
        }

        try:
            async for event in orch.handle_message(session_id, request.message):
                store.save_event(session_id, event.event_type, event.data)
                yield {
                    "event": event.event_type,
                    "data": json.dumps(event.data),
                }
        except Exception as exc:
            logger.error(
                "chat_stream_error",
                session_id=session_id,
                error=str(exc),
                exc_info=True,
            )
            yield {
                "event": "error_recovery",
                "data": json.dumps({
                    "error": "An internal error occurred. Please try again.",
                }),
            }

        store.save_session(session_id, status="completed")

        asyncio.create_task(_run_reflection(session_id, orch, store))

        yield {
            "event": "done",
            "data": json.dumps({"session_id": session_id}),
        }

    return EventSourceResponse(event_stream())


@router.get("/chat/{session_id}/status", response_model=SessionStatusResponse)
async def session_status(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> SessionStatusResponse:
    orch = get_orchestrator()
    state = orch.get_session(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionStatusResponse(
        session_id=state.session_id,
        status=state.status,
        step_count=state.step_count,
        workspace_path=str(state.workspace.path),
    )


@router.post("/chat/{session_id}/approve", response_model=ApprovalResponse)
async def approve_execution(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> ApprovalResponse:
    orch = get_orchestrator()
    if orch.approve_session(session_id):
        return ApprovalResponse(
            session_id=session_id,
            status="approved",
            message="Execution approved. The agent will proceed.",
        )
    raise HTTPException(status_code=404, detail="No pending approval for this session")


@router.post("/chat/{session_id}/reject", response_model=ApprovalResponse)
async def reject_execution(
    session_id: str,
    request: ApprovalRequest,
    _: Any = Depends(verify_api_key),
) -> ApprovalResponse:
    orch = get_orchestrator()
    if orch.reject_session(session_id, request.feedback):
        return ApprovalResponse(
            session_id=session_id,
            status="rejected",
            message="Execution rejected.",
        )
    raise HTTPException(status_code=404, detail="No pending approval for this session")
