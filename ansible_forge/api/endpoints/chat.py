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

    try:
        from ansible_forge.knowledge.consolidation import consolidate_experiences

        total = orch._experience_store.count()
        rule_count = orch._experience_store.count("rule")
        if total >= 10 and total // 15 > rule_count:
            rules_created = await consolidate_experiences(
                orch._experience_store, orch._llm
            )
            if rules_created:
                logger.info("auto_consolidation_complete", rules_created=rules_created)
                pruned = orch._experience_store.prune_subsumed()
                if pruned:
                    logger.info("auto_prune_subsumed", removed=pruned)
        deduped = orch._experience_store.deduplicate()
        if deduped:
            logger.info("auto_dedup_complete", removed=deduped)
    except Exception:
        logger.debug("auto_consolidation_failed", session_id=session_id, exc_info=True)


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
                store.save_event(session_id, event.event_type, event.data, seq=seq)
    except Exception as exc:
        logger.error(
            "chat_background_error",
            session_id=session_id,
            error=str(exc),
            exc_info=True,
        )
        error_data = _classify_error(str(exc))
        store.save_event(session_id, "error_recovery", error_data)
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
                store.save_session(session_id, status=final_status)
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

        if not session_destroyed:
            try:
                asyncio.create_task(_run_reflection(session_id, orch, store))
            except Exception:
                logger.debug("finally_reflection_failed", session_id=session_id, exc_info=True)


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
    session_id = request.session_id
    if session_id is None:
        state = orch.create_session(project_path=request.project_path)
        session_id = state.session_id

    store = _get_session_store()
    await store.asave_session(session_id, status="active", project_path=request.project_path)
    await store.asave_event(session_id, "user_message", {"content": request.message})

    bus = EventBusRegistry.get_instance().get_or_create(session_id)
    bus_gen = bus.mark_running()

    asyncio.create_task(
        _run_agent_background(session_id, request.message, orch, store, bus_gen)
    )

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
