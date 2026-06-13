"""Main conversational chat endpoint with SSE streaming.

The agent runs as a background task writing to an event bus.  The SSE
endpoint reads from the bus, so clients can disconnect and reconnect
without killing the agent.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from ansible_forge.agent.event_bus import EventBusRegistry
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

def _get_session_store() -> SessionStore:
    return SessionStore.get_instance()

router = APIRouter()

_orchestrator: Orchestrator | None = None
_active_tasks: dict[str, asyncio.Task[None]] = {}


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


async def _run_agent_background(
    session_id: str,
    message: str,
    orch: Orchestrator,
    store: SessionStore,
    bus_gen: int,
) -> None:
    bus = EventBusRegistry.get_instance().get_or_create(session_id)
    gen = bus_gen
    transient_events = frozenset({"thinking_delta", "message_delta", "progress", "live_log", "usage"})
    try:
        async for event in orch.handle_message(session_id, message):
            seq = bus.publish(event.event_type, event.data)
            if event.event_type not in transient_events:
                await store.asave_event(session_id, event.event_type, event.data, seq=seq)
    except Exception as exc:
        logger.error(
            "chat_background_error",
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )
        error_data = _classify_error(str(exc))
        await store.asave_event(session_id, "error_recovery", error_data)
        bus.publish("error_recovery", error_data)
    finally:
        final_status = "error"
        session_destroyed = False
        try:
            state = orch.get_session(session_id)
            if state is None:
                session_destroyed = True
            else:
                final_status = state.status.value
        except Exception:
            logger.debug("finally_get_session_failed", session_id=session_id, exc_info=True)

        if not session_destroyed:
            try:
                await asyncio.shield(
                    store.asave_session(session_id, status=final_status)
                )
            except Exception:
                logger.debug("finally_save_session_failed", session_id=session_id, exc_info=True)

        if bus.is_current_run(gen):
            try:
                bus.publish("done", {"session_id": session_id, "status": final_status})
            except Exception:
                logger.debug("finally_publish_done_failed", session_id=session_id, exc_info=True)

        try:
            bus.mark_done(gen)
        except Exception:
            logger.debug("finally_mark_done_failed", session_id=session_id, exc_info=True)



def _classify_error(error_msg: str) -> dict[str, str]:
    err_lower = error_msg.lower()
    cause = "unknown"
    hint = "Check the backend logs for details."

    if "api key" in err_lower or "authentication" in err_lower or "401" in err_lower:
        cause = "auth"
        hint = "Your API key appears invalid or missing. Open Settings and check your provider API key."
    elif "rate limit" in err_lower or "429" in err_lower or "too many" in err_lower:
        cause = "rate_limit"
        hint = "You've hit the provider's rate limit. Wait a moment and try again."
    elif "model" in err_lower and ("not found" in err_lower or "does not exist" in err_lower or "404" in err_lower):
        cause = "model_not_found"
        hint = "The configured model was not found. Open Settings and verify the model name."
    elif "timeout" in err_lower or "timed out" in err_lower:
        cause = "timeout"
        hint = "The LLM provider timed out. Try again or switch to a different provider."
    elif "connection" in err_lower or "connect" in err_lower or "unreachable" in err_lower:
        cause = "connection"
        hint = "Cannot reach the LLM provider. Check your internet connection or API base URL."
    elif "quota" in err_lower or "billing" in err_lower or "insufficient" in err_lower:
        cause = "quota"
        hint = "Your provider account may have insufficient credits or quota. Check your provider dashboard."

    return {"error": error_msg, "cause": cause, "hint": hint}


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    _: Any = Depends(verify_api_key),
) -> EventSourceResponse | ChatResponse:
    orch = get_orchestrator()
    session_id: str
    if request.session_id is None:
        state = await orch.create_session(project_path=request.project_path)
        session_id = state.session_id
    else:
        session_id = request.session_id

    store = _get_session_store()
    await store.asave_session(session_id, status="active", project_path=request.project_path)
    await store.asave_event(session_id, "user_message", {"content": request.message})

    prev_task = _active_tasks.get(session_id)
    if prev_task and not prev_task.done():
        prev_state = orch.get_session(session_id)
        if prev_state is not None:
            prev_state._generation += 1
            prev_state.cancel_active_work()
            orch._approval_gate.cleanup(session_id)
            orch._secret_vault.for_session(session_id).cancel_all_pending()
        prev_task.cancel()
        logger.info("cancelled_previous_run", session_id=session_id)

    bus = EventBusRegistry.get_instance().get_or_create(session_id)
    bus_gen = bus.mark_running()

    task = asyncio.create_task(
        _run_agent_background(session_id, request.message, orch, store, bus_gen)
    )
    _active_tasks[session_id] = task

    def _cleanup_task(t: asyncio.Task[None], sid: str = session_id) -> None:
        if _active_tasks.get(sid) is t:
            _active_tasks.pop(sid, None)

    task.add_done_callback(_cleanup_task)

    subscriber = bus.subscribe(from_seq=0)

    async def event_stream():  # type: ignore[return]
        yield {
            "event": "session_started",
            "data": json.dumps({"session_id": session_id}),
        }

        try:
            while True:
                try:
                    item = await asyncio.wait_for(subscriber.get(), timeout=300)
                except TimeoutError:
                    yield {
                        "event": "reconnect",
                        "data": json.dumps({
                            "session_id": session_id,
                            "reason": "idle_timeout",
                        }),
                    }
                    break
                if item is None:
                    break
                yield {
                    "event": item["event"],
                    "id": str(item.get("seq", "")),
                    "data": json.dumps(item["data"]),
                }
        finally:
            bus.unsubscribe(subscriber)

    return EventSourceResponse(event_stream(), ping=15)


@router.get("/chat/{session_id}/stream")
async def reconnect_stream(
    session_id: str,
    from_seq: int = Query(0, ge=0),
    _: Any = Depends(verify_api_key),
) -> EventSourceResponse:
    bus = EventBusRegistry.get_instance().get(session_id)
    if bus is None:
        raise HTTPException(status_code=404, detail="No active agent for this session")

    store = _get_session_store()
    has_gap = from_seq > 0 and bus.min_seq > from_seq
    missed: list[dict[str, Any]] = []
    if has_gap:
        missed = store.get_events_since_seq(session_id, from_seq)
        logger.info(
            "sse_replay_from_store",
            session_id=session_id,
            from_seq=from_seq,
            buffer_min=bus.min_seq,
            replayed=len(missed),
        )

    replay_up_to = missed[-1]["seq"] if missed else from_seq
    subscriber = bus.subscribe(from_seq=max(replay_up_to, from_seq))

    async def event_stream():  # type: ignore[return]
        try:
            for evt in missed:
                yield {
                    "event": evt["event_type"],
                    "id": str(evt["seq"]),
                    "data": json.dumps(evt["data"]),
                }
            while True:
                try:
                    item = await asyncio.wait_for(subscriber.get(), timeout=300)
                except TimeoutError:
                    yield {
                        "event": "reconnect",
                        "data": json.dumps({
                            "session_id": session_id,
                            "reason": "idle_timeout",
                        }),
                    }
                    break
                if item is None:
                    break
                yield {
                    "event": item["event"],
                    "id": str(item.get("seq", "")),
                    "data": json.dumps(item["data"]),
                }
        finally:
            bus.unsubscribe(subscriber)

    return EventSourceResponse(event_stream(), ping=15)


@router.post("/chat/{session_id}/cancel")
async def cancel_session(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    task = _active_tasks.get(session_id)
    if task is None or task.done():
        raise HTTPException(status_code=404, detail="No active run for this session")

    orch = get_orchestrator()
    state = orch.get_session(session_id)
    if state is not None:
        from ansible_forge.agent.types import SessionStatus

        state._generation += 1
        state.cancel_active_work()
        state.status = SessionStatus.COMPLETED

        orch._approval_gate.cleanup(session_id)
        orch._secret_vault.for_session(session_id).cancel_all_pending()

    task.cancel()
    logger.info("session_cancelled_by_user", session_id=session_id)

    bus = EventBusRegistry.get_instance().get(session_id)
    if bus is not None:
        cancel_gen = bus.mark_running()
        bus.publish("done", {"session_id": session_id, "status": "cancelled"})
        bus.mark_done(cancel_gen)

    return {"session_id": session_id, "status": "cancelled"}


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


class ApproveRequest(BaseModel):
    response_data: dict[str, Any] | None = Field(
        default=None,
        description="Optional config form values submitted with the approval",
    )


@router.post("/chat/{session_id}/approve", response_model=ApprovalResponse)
async def approve_execution(
    session_id: str,
    request: ApproveRequest | None = None,
    _: Any = Depends(verify_api_key),
) -> ApprovalResponse:
    orch = get_orchestrator()
    data = request.response_data if request else None
    if orch.approve_session(session_id, response_data=data):
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


@router.get("/chat/{session_id}/plan")
async def get_plan(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    orch = get_orchestrator()
    plan = orch.get_plan(session_id)
    if plan is None:
        return {"steps": [], "status": "none"}
    return plan


@router.put("/chat/{session_id}/plan")
async def update_plan(
    session_id: str,
    body: dict[str, Any],
    _: Any = Depends(verify_api_key),
) -> dict[str, str]:
    orch = get_orchestrator()
    steps = body.get("steps", [])
    if not orch.update_plan(session_id, steps):
        raise HTTPException(status_code=404, detail="Session or plan not found")
    return {"status": "updated"}
