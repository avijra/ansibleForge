"""ReAct-loop orchestrator — the brain of AnsibleForge."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from ansible_forge.agent.llm_client import LLMClient, LLMResponse, ToolCall, _repair_json
from ansible_forge.agent.memory import Memory
from ansible_forge.agent.planner import build_context
from ansible_forge.agent.prompts.system import SYSTEM_PROMPT
from ansible_forge.agent.prompts.templates import ERROR_RECOVERY_PROMPT
from ansible_forge.config import Settings, get_settings
from ansible_forge.knowledge.context import build_knowledge_context
from ansible_forge.knowledge.extractor import ingest_tool_result
from ansible_forge.knowledge.graph import KnowledgeGraph
from ansible_forge.logging import get_logger
from ansible_forge.safety.approval import ApprovalGate, ApprovalStatus
from ansible_forge.safety.diff_analyzer import DiffAnalyzer
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.safety.validators import PlaybookValidator
from ansible_forge.tools.base import ToolResult, ToolStatus
from ansible_forge.tools.registry import ToolRegistry, create_default_registry
from ansible_forge.workspace.manager import Workspace, WorkspaceManager

logger = get_logger(__name__)


PROGRESS_CHECK_PROMPT = (
    "You have been running for {step_count} steps. You MUST now do ONE of the "
    "following:\n"
    "1. If the task is complete — stop calling tools and give your final answer.\n"
    "2. If you are close to finishing — make at most 5 more tool calls, then "
    "present your final answer.\n"
    "3. If you are stuck — stop immediately and explain what is blocking you.\n\n"
    "Do NOT continue indefinitely. Summarise progress so far and wrap up."
)

LOOP_BREAK_PROMPT = (
    "STOP. You are stuck in a loop — you have been repeating the same actions. "
    "Do NOT call any more tools. Instead, respond with a final summary of:\n"
    "- What you accomplished\n"
    "- What you were unable to complete and why\n"
    "- What the user should do next\n\n"
    "Respond NOW with your final answer."
)


class SessionState:
    """Tracks state for a single agent session."""

    def __init__(self, session_id: str, workspace: Workspace) -> None:
        self.session_id = session_id
        self.workspace = workspace
        self.memory = Memory()
        self.step_count = 0
        self.status: str = "active"
        self.last_error: str | None = None
        self._recent_tool_calls: list[str] = []
        self._progress_warned = False
        self._loop_break_count = 0
        self._consecutive_errors = 0
        self._max_error_retries = 3

    def record_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        sig = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        self._recent_tool_calls.append(sig)
        if len(self._recent_tool_calls) > 20:
            self._recent_tool_calls.pop(0)

    @property
    def loop_pattern(self) -> str | None:
        """Detect multiple loop patterns, not just exact repeats.

        Catches:
        - Same tool+args repeated 3+ times
        - Alternating A-B-A-B pattern over 6 calls
        - Same tool name (any args) called 6+ times in a row
        """
        calls = self._recent_tool_calls
        if len(calls) < 3:
            return None

        # Pattern 1: exact same call 3+ times in a row
        if len(calls) >= 3 and len(set(calls[-3:])) == 1:
            return "exact_repeat"

        # Pattern 2: A-B-A-B alternation over last 6 calls
        if len(calls) >= 6:
            last6 = calls[-6:]
            if last6[0] == last6[2] == last6[4] and last6[1] == last6[3] == last6[5]:
                return "alternating"

        # Pattern 3: same tool name (ignoring args) 12+ times in a row
        # Threshold is high because scaffolding tasks legitimately write many files.
        if len(calls) >= 12:
            names = [c.split(":", 1)[0] for c in calls[-12:]]
            if len(set(names)) == 1:
                return "same_tool_drift"

        return None


class AgentEvent:
    """An event emitted during agent execution for streaming to clients."""

    def __init__(self, event_type: str, data: dict[str, Any]) -> None:
        self.event_type = event_type
        self.data = data

    def to_sse(self) -> dict[str, Any]:
        return {"event": self.event_type, "data": self.data}


class Orchestrator:
    """ReAct-loop agent orchestrator.

    Receives user messages, reasons via LLM, dispatches tools, observes
    results, and loops until the task is complete or approval is needed.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        registry: ToolRegistry | None = None,
        llm: LLMClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._registry = registry or create_default_registry()
        self._llm = llm or LLMClient(self._settings)
        self._workspace_mgr = WorkspaceManager()
        self._approval_gate = ApprovalGate()
        self._secret_vault = SecretVault.get_instance()
        self._validator = PlaybookValidator()
        self._diff_analyzer = DiffAnalyzer()
        self._sessions: dict[str, SessionState] = {}

        if self._settings.knowledge_enabled:
            global_path = self._settings.knowledge_dir / "global.kuzu"
            self._global_graph: KnowledgeGraph | None = KnowledgeGraph(global_path)
        else:
            self._global_graph = None

    def create_session(self, session_id: str | None = None) -> SessionState:
        sid = session_id or uuid.uuid4().hex[:12]
        workspace = self._workspace_mgr.create(sid)
        state = SessionState(session_id=sid, workspace=workspace)
        state.memory.attach_vault(self._secret_vault.for_session(sid))
        state.memory.add_system(SYSTEM_PROMPT)
        self._sessions[sid] = state
        logger.info("session_created", session_id=sid)
        return state

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    async def handle_message(
        self, session_id: str, user_message: str
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message through the ReAct loop, yielding events."""
        state = self._sessions.get(session_id)
        if state is None:
            state = self.create_session(session_id)

        context = build_context(state.workspace)
        kg_context = build_knowledge_context(
            self._global_graph,
            self._project_graph(state),
            state.memory.messages,
        )
        full_context = f"{user_message}\n\n---\nWorkspace context:\n{context}"
        if kg_context:
            full_context += f"\n{kg_context}"
        state.memory.add_user(full_context)

        async for event in self._react_loop(state):
            yield event

    async def _react_loop(self, state: SessionState) -> AsyncIterator[AgentEvent]:
        """Core ReAct loop: Reason → Act → Observe, repeat."""
        max_steps = self._settings.max_agent_steps
        progress_check_interval = max(max_steps // 5, 8)
        llm_timeout = 120

        while state.step_count < max_steps:
            state.step_count += 1
            logger.info(
                "react_step",
                session_id=state.session_id,
                step=state.step_count,
            )

            yield AgentEvent("step_start", {"step": state.step_count})

            # ── Progress checkpoint (fires every N steps) ────────────
            if (
                state.step_count > 1
                and state.step_count % progress_check_interval == 0
            ):
                state.memory.add_user(
                    PROGRESS_CHECK_PROMPT.format(step_count=state.step_count)
                )
                logger.info(
                    "progress_check",
                    session_id=state.session_id,
                    step=state.step_count,
                )

            # ── Validate message integrity before every LLM call ─────────
            repairs = state.memory.ensure_integrity()
            if repairs:
                logger.warning(
                    "message_integrity_repaired",
                    session_id=state.session_id,
                    repairs=repairs,
                    step=state.step_count,
                )

            # ── Loop detection: hard stop after 2 loop-break attempts ──
            if state._loop_break_count >= 2:
                logger.warning(
                    "force_stop_after_loops",
                    session_id=state.session_id,
                    step=state.step_count,
                )
                fs_response = None
                try:
                    fs_response = await asyncio.wait_for(
                        self._llm.complete(messages=state.memory.messages, tools=None),
                        timeout=llm_timeout,
                    )
                    content = fs_response.content or "Task ended — the agent was unable to converge."
                    usage = fs_response.usage
                except TimeoutError:
                    content = "Task ended — the LLM timed out while generating a final response."
                    usage = {}
                state.memory.add_assistant(
                    content=content,
                    reasoning_content=fs_response.reasoning_content if fs_response else None,
                    raw_message=fs_response.raw_message if fs_response else None,
                )
                state.status = "completed"
                yield AgentEvent("message", {"content": content, "usage": usage})
                return

            logger.info(
                "llm_call_start",
                session_id=state.session_id,
                step=state.step_count,
                message_count=state.memory.message_count,
            )

            response: LLMResponse | None = None
            streamed = False
            try:
                async with asyncio.timeout(llm_timeout):
                    async for item in self._stream_llm_call(
                        state, self._registry.to_openai_tools()
                    ):
                        if isinstance(item, LLMResponse):
                            response = item
                        else:
                            yield item
                streamed = True
            except TimeoutError:
                logger.error(
                    "llm_timeout",
                    session_id=state.session_id,
                    step=state.step_count,
                )
                state.memory.add_user(
                    "The LLM call timed out. Simplify your approach — "
                    "stop calling tools and present what you have so far."
                )
                yield AgentEvent("error_recovery", {
                    "tool": "llm",
                    "error": "LLM call timed out — context may be too large.",
                })
                continue
            except Exception as stream_exc:
                logger.warning(
                    "stream_fallback",
                    session_id=state.session_id,
                    error=str(stream_exc),
                )
                try:
                    response = await asyncio.wait_for(
                        self._llm.complete(
                            messages=state.memory.messages,
                            tools=self._registry.to_openai_tools(),
                        ),
                        timeout=llm_timeout,
                    )
                except TimeoutError:
                    state.memory.add_user(
                        "The LLM call timed out. Simplify your approach — "
                        "stop calling tools and present what you have so far."
                    )
                    yield AgentEvent("error_recovery", {
                        "tool": "llm",
                        "error": "LLM call timed out — context may be too large.",
                    })
                    continue

            if response is None:
                yield AgentEvent("error_recovery", {
                    "tool": "llm",
                    "error": "LLM returned an empty response.",
                })
                continue

            # ── Log the full LLM response ──────────────────────────────
            logger.info(
                "llm_response",
                session_id=state.session_id,
                step=state.step_count,
                has_tool_calls=response.has_tool_calls,
                tool_count=len(response.tool_calls),
                content_length=len(response.content) if response.content else 0,
                finish_reason=response.finish_reason,
                usage=response.usage,
                has_reasoning=response.reasoning_content is not None,
            )

            if not response.has_tool_calls:
                state.memory.add_assistant(
                    content=response.content,
                    reasoning_content=response.reasoning_content,
                    raw_message=response.raw_message,
                )
                state.status = "completed"
                yield AgentEvent("message", {
                    "content": response.content or "",
                    "usage": response.usage,
                })
                return

            tool_calls_raw = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                }
                for tc in response.tool_calls
            ]
            state.memory.add_assistant(
                content=response.content,
                tool_calls=tool_calls_raw,
                reasoning_content=response.reasoning_content,
                raw_message=response.raw_message,
            )

            if not streamed:
                if response.reasoning_content:
                    yield AgentEvent("thinking", {"content": response.reasoning_content})
                if response.content:
                    yield AgentEvent("thinking", {"content": response.content})

            loop_broken = False
            for tc in response.tool_calls:
                state.record_tool_call(tc.name, tc.arguments)

                pattern = state.loop_pattern
                if pattern:
                    state._loop_break_count += 1
                    logger.warning(
                        "loop_detected",
                        session_id=state.session_id,
                        tool=tc.name,
                        pattern=pattern,
                        step=state.step_count,
                        break_count=state._loop_break_count,
                    )
                    # Add tool results for ALL remaining tool calls
                    # (current tc and any after it) to keep message integrity.
                    remaining_idx = response.tool_calls.index(tc)
                    for remaining_tc in response.tool_calls[remaining_idx:]:
                        state.memory.add_tool_result(
                            remaining_tc.id,
                            '{"status":"error","output":"Tool call skipped — loop detected."}',
                        )
                    state.memory.add_user(LOOP_BREAK_PROMPT)
                    yield AgentEvent("error_recovery", {
                        "tool": tc.name,
                        "error": f"Loop detected ({pattern}) — forcing agent to wrap up.",
                    })
                    loop_broken = True
                    break

                session_vault = self._secret_vault.for_session(state.session_id)

                logger.info(
                    "tool_call",
                    session_id=state.session_id,
                    step=state.step_count,
                    tool=tc.name,
                    tool_call_id=tc.id,
                    arguments=session_vault.redact_dict(tc.arguments),
                )

                yield AgentEvent("tool_call", session_vault.redact_dict({
                    "tool": tc.name,
                    "arguments": tc.arguments,
                    "tool_call_id": tc.id,
                }))

                result = await self._execute_tool(state, tc.name, tc.arguments)

                logger.info(
                    "tool_result",
                    session_id=state.session_id,
                    step=state.step_count,
                    tool=tc.name,
                    tool_call_id=tc.id,
                    status=result.status.value,
                    output_preview=result.output[:500] if result.output else "",
                )

                # For secret requests, defer adding tool result until
                # the secret is provided (avoids duplicate tool_call_id).
                if (
                    result.status == ToolStatus.NEEDS_APPROVAL
                    and result.data.get("secret_request")
                ):
                    secret_name = result.data["secret_name"]
                    secret_desc = result.data["secret_description"]
                    sensitive_type = result.data.get("sensitive_type", "other")
                    state.status = "awaiting_secret"

                    yield AgentEvent("secret_request", {
                        "session_id": state.session_id,
                        "secret_name": secret_name,
                        "secret_description": secret_desc,
                        "sensitive_type": sensitive_type,
                    })

                    pending_evt = session_vault.create_pending(secret_name)
                    try:
                        await asyncio.wait_for(pending_evt.wait(), timeout=600)
                    except TimeoutError:
                        state.status = "active"
                        session_vault.cleanup_pending(secret_name)
                        timeout_msg = (
                            f"Secret '{secret_name}' was not provided within the timeout. "
                            "You may ask the user to retry or proceed without it."
                        )
                        state.memory.add_tool_result(tc.id, timeout_msg)
                        yield AgentEvent("tool_result", {
                            "tool": tc.name,
                            "tool_call_id": tc.id,
                            "status": "error",
                            "output": timeout_msg,
                        })
                        continue
                    finally:
                        session_vault.cleanup_pending(secret_name)

                    state.status = "active"
                    confirm = (
                        f"Secret '{secret_name}' has been securely stored. "
                        f"Use the variable name `{secret_name}` in playbooks and templates — "
                        f"the real value will be injected automatically at execution time. "
                        f"NEVER include the actual secret value in any generated content."
                    )
                    state.memory.add_tool_result(tc.id, confirm)
                    yield AgentEvent("tool_result", {
                        "tool": tc.name,
                        "tool_call_id": tc.id,
                        "status": "success",
                        "output": confirm,
                    })
                    continue

                state.memory.add_tool_result(tc.id, result.model_dump_json())
                self._ingest_to_graph(tc.name, result, state.session_id, state)

                tool_result_payload: dict[str, Any] = {
                    "tool": tc.name,
                    "tool_call_id": tc.id,
                    "status": result.status.value,
                    "output": result.output[:2000],
                }
                if result.data:
                    tool_result_payload["data"] = result.data
                yield AgentEvent("tool_result", session_vault.redact_dict(
                    tool_result_payload
                ))

                if result.status == ToolStatus.NEEDS_APPROVAL:
                    state.status = "awaiting_approval"
                    yield AgentEvent("approval_required", {
                        "session_id": state.session_id,
                        "output": result.output,
                        "data": result.data,
                    })

                    approval = self._approval_gate.create_request(
                        session_id=state.session_id,
                        description=f"Execute {tc.name}",
                        diff_summary=result.output,
                        metadata=result.data,
                    )

                    status = await approval.wait(timeout=600)
                    if status == ApprovalStatus.APPROVED:
                        state.status = "active"
                        yield AgentEvent("approval_granted", {"session_id": state.session_id})
                    else:
                        state.status = "rejected"
                        feedback = approval.feedback or "User rejected the operation."
                        state.memory.add_user(f"User rejected: {feedback}")
                        yield AgentEvent("approval_rejected", {
                            "session_id": state.session_id,
                            "feedback": feedback,
                        })
                        return

                if result.status == ToolStatus.ERROR:
                    state._consecutive_errors += 1
                    state.last_error = result.error
                    remaining = max(state._max_error_retries - state._consecutive_errors, 0)
                    error_ctx = ERROR_RECOVERY_PROMPT.format(
                        tool_name=tc.name,
                        error_message=result.error or "Unknown error",
                        remaining_retries=remaining,
                    )
                    state.memory.add_user(error_ctx)
                    yield AgentEvent("error_recovery", {
                        "tool": tc.name,
                        "error": result.error,
                        "retries_remaining": remaining,
                    })
                else:
                    state._consecutive_errors = 0

            if loop_broken:
                continue

        state.status = "max_steps_reached"
        yield AgentEvent("max_steps", {
            "step_count": state.step_count,
            "message": f"Agent reached the maximum of {max_steps} steps.",
        })

    async def _stream_llm_call(
        self,
        state: SessionState,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[AgentEvent | LLMResponse]:
        """Stream an LLM call, yielding ``thinking_delta`` events for each token.

        The **last** item yielded is always the accumulated ``LLMResponse``.
        All preceding items are ``AgentEvent`` instances with content deltas.
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tc_accum: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, int] = {}

        async for chunk in self._llm.complete_stream(
            messages=state.memory.messages,
            tools=tools,
        ):
            if chunk.get("content"):
                content_parts.append(chunk["content"])
                yield AgentEvent("thinking_delta", {"content": chunk["content"]})

            if chunk.get("reasoning_content"):
                reasoning_parts.append(chunk["reasoning_content"])
                yield AgentEvent("thinking_delta", {"content": chunk["reasoning_content"]})

            if chunk.get("tool_calls"):
                for tc_delta in chunk["tool_calls"]:
                    idx = tc_delta.get("index", 0)
                    if idx not in tc_accum:
                        tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.get("id"):
                        tc_accum[idx]["id"] = tc_delta["id"]
                    fn = tc_delta.get("function") or {}
                    if fn.get("name"):
                        tc_accum[idx]["name"] = fn["name"]
                    if fn.get("arguments"):
                        tc_accum[idx]["arguments"] += fn["arguments"]

            if chunk.get("finish_reason"):
                finish_reason = chunk["finish_reason"]
            if chunk.get("usage"):
                usage = chunk["usage"]

        tool_calls: list[ToolCall] = []
        for idx in sorted(tc_accum):
            tc_data = tc_accum[idx]
            raw_args = tc_data["arguments"]
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = _repair_json(raw_args)
            tool_calls.append(ToolCall(id=tc_data["id"], name=tc_data["name"], arguments=args))

        yield LLMResponse(
            content="".join(content_parts) or None,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            reasoning_content="".join(reasoning_parts) or None,
        )

    def _project_graph(self, state: SessionState) -> KnowledgeGraph | None:
        if not self._settings.knowledge_enabled:
            return None
        kg_path = state.workspace.path / "knowledge" / "project.kuzu"
        return KnowledgeGraph(kg_path)

    def _ingest_to_graph(
        self, tool_name: str, result: ToolResult, session_id: str, state: SessionState
    ) -> None:
        if not self._settings.knowledge_enabled:
            return
        try:
            ingest_tool_result(
                tool_name,
                result,
                session_id,
                self._global_graph,  # type: ignore[arg-type]
                self._project_graph(state),  # type: ignore[arg-type]
            )
        except Exception:
            logger.warning("knowledge_ingest_failed", tool=tool_name, exc_info=True)

    async def _execute_tool(
        self, state: SessionState, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool, injecting workspace_path and session_id where needed."""
        if "workspace_path" in arguments:
            pass
        elif any(
            p in self._registry.get(tool_name).parameters.get("properties", {})  # type: ignore[union-attr]
            for p in ("workspace_path",)
        ):
            arguments["workspace_path"] = str(state.workspace.path)

        arguments["_session_id"] = state.session_id

        try:
            result = await self._registry.execute(tool_name, arguments)
        except Exception as exc:
            logger.error("tool_execution_error", tool=tool_name, error=str(exc))
            result = ToolResult.fail(f"Tool execution failed: {exc}")

        return result

    def store_secret(self, session_id: str, name: str, value: str, description: str = "") -> bool:
        """Store a secret in the session vault and unblock any pending request."""
        vault = self._secret_vault.for_session(session_id)
        vault.store(name, value, description)
        return True

    def list_secrets(self, session_id: str) -> list[dict[str, str]]:
        return self._secret_vault.for_session(session_id).list_names()

    def delete_secret(self, session_id: str, name: str) -> bool:
        return self._secret_vault.for_session(session_id).delete(name)

    def approve_session(self, session_id: str) -> bool:
        return self._approval_gate.approve(session_id)

    def reject_session(self, session_id: str, feedback: str = "") -> bool:
        return self._approval_gate.reject(session_id, feedback)

    def destroy_session(self, session_id: str) -> None:
        self._approval_gate.cleanup(session_id)
        self._secret_vault.destroy_session(session_id)
        self._workspace_mgr.destroy(session_id)
        self._sessions.pop(session_id, None)
        logger.info("session_destroyed", session_id=session_id)
