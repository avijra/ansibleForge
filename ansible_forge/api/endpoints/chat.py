"""Main conversational chat endpoint with SSE streaming."""

from __future__ import annotations

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

router = APIRouter()

_orchestrator: Orchestrator | None = None


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

    async def event_stream():  # type: ignore[return]
        yield {
            "event": "session_started",
            "data": json.dumps({"session_id": session_id}),
        }

        try:
            async for event in orch.handle_message(session_id, request.message):
                yield {
                    "event": event.event_type,
                    "data": json.dumps(event.data),
                }
        except Exception as exc:
            yield {
                "event": "error_recovery",
                "data": json.dumps({
                    "error": f"Agent error: {type(exc).__name__}: {exc}",
                }),
            }

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
