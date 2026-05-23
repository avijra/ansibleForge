"""ReAct-loop orchestrator — the brain of AnsibleForge."""

from __future__ import annotations

import asyncio
import contextlib
import json
import uuid
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from ansible_forge.agent import infra_tracker
from ansible_forge.agent.llm_client import LLMClient, LLMResponse, ToolCall, _repair_json
from ansible_forge.agent.memory import Memory, _estimate_message_tokens
from ansible_forge.agent.planner import build_context
from ansible_forge.agent.prompts.system import SYSTEM_PROMPT
from ansible_forge.agent.prompts.templates import ERROR_RECOVERY_PROMPT
from ansible_forge.agent.types import SessionStatus
from ansible_forge.config import Settings, get_settings
from ansible_forge.logging import get_logger
from ansible_forge.persistence.session_store import SessionStore
from ansible_forge.safety.approval import ApprovalGate, ApprovalStatus
from ansible_forge.safety.diff_analyzer import DiffAnalyzer
from ansible_forge.safety.secret_vault import SecretVault
from ansible_forge.safety.validators import PlaybookValidator
from ansible_forge.tools.base import ToolResult, ToolStatus
from ansible_forge.tools.registry import ToolRegistry, create_default_registry
from ansible_forge.workspace.checkpoints import create_checkpoint, is_file_writing_tool
from ansible_forge.workspace.context import build_mention_context
from ansible_forge.workspace.manager import Workspace, WorkspaceManager

logger = get_logger(__name__)


PROGRESS_CHECK_PROMPT = (
    "Status check — you have been running for {step_count} steps.\n"
    "If the task is complete, stop and give your final answer.\n"
    "If you are stuck in a loop, stop and explain what is blocking you.\n"
    "Otherwise, continue working — you have plenty of steps remaining."
)

LOOP_BREAK_PROMPT = (
    "Caution: you may be in a loop — the same tool has been called many times. "
    "Before your next action, briefly assess:\n"
    "1. Are you making real progress with distinct arguments each call? If YES, continue.\n"
    "2. Are you retrying the exact same call hoping for a different result? If YES, stop "
    "and explain what is blocking you.\n"
    "3. Is there a different tool or approach that would be more efficient?\n\n"
    "If you are genuinely iterating over multiple hosts/VMs/resources, that is FINE — "
    "continue your work. Only stop if you are truly stuck."
)

_PROGRESS_INTERVAL = 5
_CHUNK_DEAD_TICKS = 24

_PARALLELIZABLE_TOOLS = frozenset({
    "collect_facts", "test_connectivity", "search_docs", "web_search",
    "run_lint", "inspect_variables", "compare_configs", "detect_drift",
    "scan_compliance", "analyze_logs", "verify_state", "discover_inventory",
})

_CORE_TOOLS = frozenset({
    "read_file", "write_file", "web_search", "search_docs", "memory",
    "request_secret", "session_search", "local_exec",
})

_RECON_TOOLS = frozenset({
    "collect_facts", "test_connectivity", "discover_inventory",
    "inspect_variables", "detect_drift", "import_project",
})

_GENERATION_TOOLS = frozenset({
    "generate_playbook", "scaffold_role", "manage_inventory",
    "manage_vault", "run_lint", "manage_galaxy",
    "render_template", "generate_rollback", "manage_git",
})

_EXECUTION_VERIFY_TOOLS = frozenset({
    "execute_playbook", "run_adhoc", "verify_state",
})

_TERRAFORM_TOOLS = frozenset({
    "generate_terraform", "terraform_exec", "terraform_to_inventory",
})

_ALL_TOOL_NAMES = (
    _CORE_TOOLS | _RECON_TOOLS | _GENERATION_TOOLS
    | _EXECUTION_VERIFY_TOOLS | _TERRAFORM_TOOLS
)

_TOOL_PROGRESS_MESSAGES: dict[str, list[str]] = {
    "execute_playbook": [
        "Playbook is running — watching for task output...",
        "Playbook still executing. Complex deployments can take several minutes.",
        "Playbook continues running. Will report results when it finishes.",
        "Playbook in progress. Long-running tasks (installs, cluster ops) are expected to take time.",
        "Playbook still running — this is normal for infrastructure deployments.",
        "Playbook executing. Agent is alive and monitoring progress.",
    ],
    "collect_facts": [
        "Gathering host facts (OS, packages, network, services)...",
        "Still collecting facts — some hosts take longer to respond.",
        "Facts collection in progress. Waiting on remaining hosts.",
    ],
    "test_connectivity": [
        "Testing SSH connectivity to your hosts...",
        "Still checking connectivity — some hosts may be slow to respond.",
        "Connectivity check in progress. Will report which hosts are reachable.",
    ],
    "install_collection": [
        "Installing Ansible collection from Galaxy...",
        "Still downloading collection. Large collections take a moment.",
    ],
    "manage_galaxy": [
        "Installing Ansible collection from Galaxy...",
        "Still downloading. Large collections and dependencies take a moment.",
        "Galaxy operation in progress. Installing Python SDK dependencies if needed.",
        "Package installation continues — downloading required libraries.",
        "Almost done with collection and dependency installation.",
    ],
    "run_molecule_test": [
        "Running Molecule tests to validate the role...",
        "Tests still running — waiting for all scenarios to complete.",
        "Test execution in progress. Will report pass/fail results.",
    ],
    "search_web": [
        "Searching for relevant documentation and examples...",
        "Still fetching search results.",
    ],
    "run_adhoc": [
        "Running command on target host(s)...",
        "Command still executing. Waiting for output.",
        "Command in progress. Some operations take time to complete.",
        "Still running. Will report results when the command finishes.",
    ],
    "local_exec": [
        "Running local command...",
        "Command still executing. Waiting for output.",
        "Command in progress.",
        "Still running. Some operations take time to complete.",
    ],
    "terraform_exec": [
        "Terraform operation running...",
        "Terraform still executing. Infrastructure changes can take several minutes.",
        "Terraform in progress. Cloud resource provisioning takes time.",
        "Terraform still working. Large infrastructure changes may take 10-30 minutes.",
        "Terraform operation ongoing — agent is alive and monitoring.",
    ],
}

_DEFAULT_PROGRESS_MESSAGES = [
    "Working on this — will update you shortly.",
    "Still processing. Will report what I find.",
    "Operation in progress.",
    "Still running. Will share results when done.",
    "Agent alive — operation continues.",
]

_LLM_THINKING_MESSAGES = [
    "Analyzing the situation and deciding next steps...",
    "Reviewing results and planning the right approach...",
    "Thinking through the best course of action...",
    "Evaluating options — will explain my reasoning shortly.",
    "Almost ready with my assessment.",
]


def _estimate_step_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost for a single LLM call using litellm's pricing database."""
    try:
        import litellm
        from litellm import Choices, Message, ModelResponse, Usage

        mock_resp = ModelResponse(
            model=model,
            choices=[Choices(
                finish_reason="stop", index=0,
                message=Message(content="", role="assistant"),
            )],
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
            ),
        )
        return litellm.completion_cost(completion_response=mock_resp)
    except Exception:
        return 0.0


class SessionState:
    """Tracks state for a single agent session."""

    def __init__(self, session_id: str, workspace: Workspace) -> None:
        self.session_id = session_id
        self.workspace = workspace
        ctx_limit = get_settings().llm_max_context_tokens
        self.memory = Memory(max_context_tokens=ctx_limit)
        self.step_count = 0
        self.status: SessionStatus = SessionStatus.ACTIVE
        self.last_error: str | None = None
        self._recent_tool_calls: list[str] = []
        self._progress_warned = False
        self._loop_break_count = 0
        self._consecutive_errors = 0
        self._max_error_retries = 3
        self._generation = 0
        self._last_error_by_tool: dict[str, dict[str, Any]] = {}
        self._exec_fail_count = 0
        self._searched_since_exec_fail = False
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_cost = 0.0
        self._rejected_output: str | None = None
        self._rejected_feedback: str | None = None
        self._rejected_tool: str | None = None
        self._approved_playbooks: set[str] = set()
        self._empty_response_retries = 0
        self.plan: dict[str, Any] | None = None
        self._active_tasks: set[asyncio.Task[Any]] = set()

    def track_task(self, task: asyncio.Task[Any]) -> None:
        self._active_tasks.add(task)
        task.add_done_callback(self._active_tasks.discard)

    def cancel_active_work(self) -> None:
        for task in list(self._active_tasks):
            if not task.done():
                task.cancel()
        self._active_tasks.clear()

    def record_tool_call(self, name: str, arguments: dict[str, Any]) -> None:
        sig = f"{name}:{json.dumps(arguments, sort_keys=True)}"
        self._recent_tool_calls.append(sig)
        if len(self._recent_tool_calls) > 30:
            self._recent_tool_calls.pop(0)

    @property
    def loop_pattern(self) -> str | None:
        """Detect loop patterns that indicate the agent is stuck.

        Catches:
        - Exact same tool+args repeated 3+ times in a row (genuinely stuck)
        - Alternating A-B-A-B pattern with identical args over 6 calls
        - Same tool name with IDENTICAL args 5+ times (retrying same failing call)
        - Same tool with same error pattern 3+ times (error-identical loop)

        Does NOT flag:
        - Same tool called many times with different args (legitimate multi-host work)
        """
        calls = self._recent_tool_calls
        if len(calls) < 3:
            return None

        if len(set(calls[-3:])) == 1:
            return "exact_repeat"

        if len(calls) >= 6:
            last6 = calls[-6:]
            if (last6[0] == last6[2] == last6[4]
                    and last6[1] == last6[3] == last6[5]):
                return "alternating"

        if len(calls) >= 15:
            recent = calls[-15:]
            names = [c.split(":", 1)[0] for c in recent]
            args = [c.split(":", 1)[1] if ":" in c else "" for c in recent]
            if len(set(names)) == 1 and len(set(args)) <= 3:
                return "same_tool_drift"

        return None

    def has_repeated_errors(self) -> bool:
        """Return True if the same tool has failed with the same error 3+ times."""
        if len(self._last_error_by_tool) == 0:
            return False
        recent_names = [c.split(":", 1)[0] for c in self._recent_tool_calls[-10:]]
        for tool_name, info in self._last_error_by_tool.items():
            count = recent_names.count(tool_name)
            if count >= 3:
                return True
        return False


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
        self._session_store = SessionStore.get_instance()

    _EXECUTION_TOOLS = frozenset({"execute_playbook", "run_adhoc", "terraform_exec"})
    _SEARCH_GATE_THRESHOLD = 2
    _DYNAMIC_TOOL_RECENT_LOOKBACK = 10

    def _select_tools(self, state: SessionState) -> frozenset[str]:
        """Pick the active tool subset based on recent conversation history.

        For the first few steps, returns ALL registered tools so the model
        can discover what's available (including plugin tools).

        After step 3, starts with the full registry set and *removes*
        hardcoded categories that haven't been recently used or mentioned.
        This keeps core tools, plugin tools, and any recently-active
        category always visible.
        """
        all_registered = frozenset(self._registry.tool_names)
        if state.step_count < 3:
            return all_registered

        recent = state.memory._messages[-Orchestrator._DYNAMIC_TOOL_RECENT_LOOKBACK:]
        recent_tool_names: set[str] = set()
        mentioned_categories: set[frozenset[str]] = set()
        for m in recent:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    recent_tool_names.add(tc.get("function", {}).get("name", ""))
            content = m.get("content", "")
            if isinstance(content, str):
                lower = content.lower()
                if "terraform" in lower or "tf " in lower:
                    mentioned_categories.add(_TERRAFORM_TOOLS)
                if "playbook" in lower or "ansible" in lower or "deploy" in lower:
                    mentioned_categories.add(_GENERATION_TOOLS)
                    mentioned_categories.add(_EXECUTION_VERIFY_TOOLS)
                if "inventory" in lower or "host" in lower or "fact" in lower:
                    mentioned_categories.add(_RECON_TOOLS)

        removable: set[str] = set()
        for category in (
            _RECON_TOOLS, _GENERATION_TOOLS,
            _EXECUTION_VERIFY_TOOLS, _TERRAFORM_TOOLS,
        ):
            if category in mentioned_categories:
                continue
            if recent_tool_names & category:
                continue
            removable |= category

        removable -= _CORE_TOOLS
        removable -= recent_tool_names

        return all_registered - removable

    @staticmethod
    def _check_search_gate(state: SessionState, tool_name: str) -> ToolResult | None:
        if tool_name not in Orchestrator._EXECUTION_TOOLS:
            return None
        if state._searched_since_exec_fail:
            return None
        if state._exec_fail_count < Orchestrator._SEARCH_GATE_THRESHOLD:
            return None
        return ToolResult.fail(
            f"BLOCKED: {tool_name} has failed {state._exec_fail_count} time(s) "
            f"and you have not searched for the error. "
            f"You MUST call `web_search` with the error message before "
            f"retrying any execution tool. This is a hard requirement, "
            f"not a suggestion.",
        )

    @staticmethod
    def _build_exec_fail_directive(
        tool_name: str,
        error: str,
        fail_count: int,
        searched: bool,
    ) -> str | None:
        if tool_name not in Orchestrator._EXECUTION_TOOLS:
            return None

        error_summary = (error[:300] if error else "Unknown error").replace('"', "'")

        if fail_count >= 3 and not searched:
            return (
                f'HALT. "{tool_name}" has failed {fail_count} times and you have '
                "NOT searched for the error even once. You are in a loop.\n\n"
                "You MUST do ONE of the following — no other action is allowed:\n"
                "A) Call `web_search` with the core error message right now, OR\n"
                "B) Report to the user that you are stuck and ask for guidance.\n\n"
                "Do NOT generate another playbook. Do NOT call "
                f"`{tool_name}` again until you have search results or user input."
            )

        if fail_count >= 3 and searched:
            return (
                f'"{tool_name}" has now failed {fail_count} times. You searched '
                "the web but the fix didn't work.\n\n"
                "STOP retrying the same approach. You MUST:\n"
                "1. Tell the user exactly what you tried and what failed\n"
                "2. Share the relevant error and search results\n"
                "3. Ask the user for guidance on how to proceed\n\n"
                "Do NOT generate another playbook without user input."
            )

        if fail_count == 2 and not searched:
            return (
                f'WARNING: "{tool_name}" has failed twice without a web search.\n\n'
                "Your next action MUST be `web_search` with this error:\n"
                f'"{error_summary}"\n\n'
                "Do NOT generate another playbook until you have search results."
            )

        return (
            f'"{tool_name}" failed. Before retrying, use `web_search` to look up '
            f'the error: "{error_summary}"\n'
            "Read the results, then fix based on what you find."
        )

    _MAX_USER_RULES_CHARS = 2000

    @staticmethod
    def _load_user_rules(workspace: Workspace) -> str | None:
        rules_file = workspace.runner_dir / "rules.md"
        if not rules_file.is_file():
            return None
        try:
            content = rules_file.read_text().strip()
            if not content:
                return None
            if len(content) > Orchestrator._MAX_USER_RULES_CHARS:
                content = content[:Orchestrator._MAX_USER_RULES_CHARS] + "\n[rules truncated]"
            return content
        except Exception:
            return None

    def _build_system_prompt(self, workspace: Workspace) -> str:
        rules = self._load_user_rules(workspace)
        if not rules:
            return SYSTEM_PROMPT
        return (
            f"{SYSTEM_PROMPT}\n\n"
            f"## User Rules (from .tuyere/rules.md — ALWAYS follow these)\n\n"
            f"{rules}"
        )

    async def create_session(
        self,
        session_id: str | None = None,
        project_path: str | None = None,
    ) -> SessionState:
        sid = session_id or uuid.uuid4().hex[:12]
        loop = asyncio.get_running_loop()
        workspace = await loop.run_in_executor(
            None, partial(self._workspace_mgr.create, sid, project_path=project_path),
        )
        state = SessionState(session_id=sid, workspace=workspace)
        state.memory.attach_vault(self._secret_vault.for_session(sid))
        state.memory.add_system(self._build_system_prompt(workspace))
        self._sessions[sid] = state
        await self._session_store.asave_session(sid, project_path=str(workspace.path))
        logger.info("session_created", session_id=sid, project_path=str(workspace.path))
        return state

    def get_session(self, session_id: str) -> SessionState | None:
        return self._sessions.get(session_id)

    def update_plan(self, session_id: str, steps: list[dict[str, Any]]) -> bool:
        state = self._sessions.get(session_id)
        if state is None or state.plan is None:
            return False
        state.plan["steps"] = steps
        return True

    def get_plan(self, session_id: str) -> dict[str, Any] | None:
        state = self._sessions.get(session_id)
        if state is None:
            return None
        return state.plan

    async def _arestore_session(self, session_id: str) -> SessionState | None:
        """Restore a session from the workspace on disk.

        Instead of replaying raw conversation messages (which breaks
        reasoning-mode models that require ``reasoning_content`` passback),
        the agent receives a workspace summary and a digest of recent user
        requests.  This is model-agnostic and keeps context small.
        """
        session_meta = await self._session_store.aget_session(session_id)
        project_path = session_meta.get("project_path") if session_meta else None

        workspace = None
        if project_path:
            workspace = self._workspace_mgr.get_by_path(project_path)
        if workspace is None:
            workspace = self._workspace_mgr.get(session_id)
        if workspace is None:
            return None

        all_events = await self._session_store.aget_events(session_id)
        if not all_events:
            return None

        state = SessionState(session_id=session_id, workspace=workspace)
        state.memory.attach_vault(self._secret_vault.for_session(session_id))
        state.memory.add_system(self._build_system_prompt(workspace))

        loop = asyncio.get_running_loop()
        ws_summary = await loop.run_in_executor(
            None, self._build_workspace_summary, workspace
        )
        recent_requests = [
            e["data"].get("content", "")
            for e in all_events
            if e.get("event_type") == "user_message" and e["data"].get("content")
        ][-5:]
        recent_responses = [
            e["data"].get("content", "")
            for e in all_events
            if e.get("event_type") == "message" and e["data"].get("content")
        ][-3:]

        restore_ctx_parts = [
            "This session is being resumed after an app restart.",
            "The workspace and all previously generated files are intact.",
        ]
        if ws_summary:
            restore_ctx_parts.append(f"\n## Workspace contents\n{ws_summary}")
        if recent_requests:
            restore_ctx_parts.append(
                "\n## Recent user requests\n"
                + "\n".join(f"- {r[:200]}" for r in recent_requests)
            )
        if recent_responses:
            last_response = recent_responses[-1]
            if len(last_response) > 500:
                last_response = last_response[:500] + "…"
            restore_ctx_parts.append(
                f"\n## Last agent response (summary)\n{last_response}"
            )

        state.memory.add_user("\n".join(restore_ctx_parts))
        state.memory.add_assistant(
            content=(
                "Understood — I have the full workspace context from our prior session. "
                "I can see the existing playbooks, inventory, and other files. "
                "How would you like to continue?"
            )
        )

        self._sessions[session_id] = state
        logger.info(
            "session_restored",
            session_id=session_id,
            total_events=len(all_events),
            workspace=str(workspace.path),
        )
        return state

    @staticmethod
    def _build_workspace_summary(workspace: Workspace) -> str:
        parts: list[str] = []
        project = workspace.project_dir
        inventory = workspace.inventory_dir

        if project.exists():
            playbooks = list(project.glob("*.yml")) + list(project.glob("*.yaml"))
            if playbooks:
                parts.append(
                    "Playbooks: " + ", ".join(p.name for p in playbooks)
                )
            roles = [d.name for d in (project / "roles").iterdir()] if (project / "roles").is_dir() else []
            if roles:
                parts.append("Roles: " + ", ".join(roles))

        if inventory.exists():
            inv_files = list(inventory.iterdir())
            if inv_files:
                parts.append(
                    "Inventory: " + ", ".join(f.name for f in inv_files)
                )

        return "\n".join(parts)

    async def handle_message(
        self, session_id: str, user_message: str
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message through the ReAct loop, yielding events."""
        state = self._sessions.get(session_id)
        if state is None:
            state = await self._arestore_session(session_id)
        if state is None:
            state = await self.create_session(session_id)

        state._generation += 1
        state.cancel_active_work()

        if state.status == SessionStatus.AWAITING_SECRET:
            session_vault = self._secret_vault.for_session(session_id)
            session_vault.cancel_all_pending()
            logger.info("secret_wait_cancelled", session_id=session_id)

        if state.status == SessionStatus.AWAITING_APPROVAL:
            self._approval_gate.cleanup(session_id)

        state.status = SessionStatus.ACTIVE
        await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        try:
            context = await loop.run_in_executor(None, build_context, state.workspace)
        except Exception:
            logger.warning("build_context_failed", session_id=session_id, exc_info=True)
            context = ""

        mention_context = ""
        try:
            mention_context = await loop.run_in_executor(
                None, build_mention_context, state.workspace.path, user_message
            )
        except Exception:
            logger.debug("mention_context_failed", exc_info=True)

        ws_memory_context = ""
        try:
            from ansible_forge.knowledge.workspace_memory import WorkspaceMemory
            ws_path = str(state.workspace.path) if state.workspace else ""
            ws_id = ws_path.replace("/", "_").replace("\\", "_").strip("_") or "default"
            ws_memory_context = await loop.run_in_executor(
                None, WorkspaceMemory(ws_id).inject_context
            )
        except Exception:
            logger.debug("workspace_memory_inject_failed", exc_info=True)

        full_context = f"{user_message}\n\n---\nWorkspace context:\n{context}"
        if mention_context:
            full_context += f"\n{mention_context}"
        if ws_memory_context:
            full_context += f"\n{ws_memory_context}"
        _max_ctx = 12000
        if len(full_context) > _max_ctx:
            user_len = len(user_message)
            available = _max_ctx - user_len - 100
            if available > 500:
                full_context = f"{user_message}\n\n---\nWorkspace context:\n{context[:available]}\n[context truncated]"
            else:
                full_context = user_message[:_max_ctx]
        state.memory.add_user(full_context)

        plan = await self._generate_plan(state, user_message)
        if plan:
            yield AgentEvent("plan", plan)

        async for event in self._react_loop(state):
            yield event

    async def _react_loop(self, state: SessionState) -> AsyncIterator[AgentEvent]:
        """Core ReAct loop: Reason → Act → Observe, repeat."""
        import time as _time

        max_steps = self._settings.max_agent_steps
        progress_check_interval = max(max_steps // 3, 15)
        llm_timeout = 600
        consecutive_llm_timeouts = 0
        max_consecutive_llm_timeouts = 3
        my_generation = state._generation
        yielded_terminal = False
        session_start_mono = _time.monotonic()
        last_activity_mono = session_start_mono
        stall_warning_secs = 300  # 5 minutes
        stall_recovery_secs = 900  # 15 minutes
        _stall_warned = False
        max_session_duration = getattr(self._settings, "session_timeout_seconds", 7200)

        try:
          while state.step_count < max_steps:
            # Wall-clock timeout guard
            elapsed = _time.monotonic() - session_start_mono
            if elapsed > max_session_duration:
                state.status = SessionStatus.COMPLETED
                logger.warning(
                    "session_wall_clock_timeout",
                    session_id=state.session_id,
                    elapsed_seconds=int(elapsed),
                )
                yield AgentEvent("timeout", {
                    "elapsed_seconds": int(elapsed),
                    "reason": "wall_clock",
                })
                state.status = SessionStatus.COMPLETED
                yielded_terminal = True
                yield AgentEvent("message", {
                    "content": (
                        f"Session timed out after {int(elapsed // 60)} minutes. "
                        "Please start a new session to continue."
                    ),
                })
                return

            if state._generation != my_generation:
                logger.info("react_loop_superseded", session_id=state.session_id)
                return
            try:
                state.step_count += 1
                logger.info(
                    "react_step",
                    session_id=state.session_id,
                    step=state.step_count,
                )

                yield AgentEvent("step_start", {"step": state.step_count})

                # ── Stall detection ────────────────────────────────────
                stall_elapsed = _time.monotonic() - last_activity_mono
                if stall_elapsed > stall_recovery_secs:
                    state.memory.add_user(
                        "You appear to be stalled — no meaningful progress for "
                        f"{int(stall_elapsed)} seconds. Summarize your current state "
                        "and ask the user for help if you are stuck."
                    )
                    yield AgentEvent("progress", {
                        "tool": "stall_detection",
                        "message": f"No progress for {int(stall_elapsed)}s — injecting recovery.",
                    })
                    last_activity_mono = _time.monotonic()
                    _stall_warned = False
                elif stall_elapsed > stall_warning_secs and not _stall_warned:
                    yield AgentEvent("progress", {
                        "tool": "stall_detection",
                        "message": f"Agent has been working for {int(stall_elapsed)}s without new results.",
                    })
                    _stall_warned = True

                # ── Step budget warning (fires at 40 steps) ──────────────
                if state.step_count == 40:
                    state.memory.add_user(
                        "BUDGET WARNING: You have used 40 steps. This is excessive for "
                        "most tasks. You MUST wrap up within 10 more steps. If you cannot "
                        "complete the task, summarize what you accomplished, what remains, "
                        "and ask the user how to proceed. Do NOT keep iterating."
                    )
                    logger.warning(
                        "step_budget_warning",
                        session_id=state.session_id,
                        step=state.step_count,
                    )

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

                # ── LLM compaction: summarize old turns when context is large ──
                if state.step_count > 0 and state.step_count % 10 == 0:
                    try:
                        compacted = await state.memory.compact_with_llm(self._llm)
                        if compacted:
                            logger.info(
                                "conversation_compacted_by_llm",
                                session_id=state.session_id,
                                step=state.step_count,
                            )
                    except Exception:
                        logger.warning(
                            "compaction_failed",
                            session_id=state.session_id,
                            step=state.step_count,
                            exc_info=True,
                        )

                # ── Compress old tool results to reduce context size ────────
                compressed = state.memory.compress_old_tool_results(keep_recent=20)
                if compressed:
                    logger.info(
                        "tool_results_compressed",
                        session_id=state.session_id,
                        count=compressed,
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

                # ── Loop detection: hard stop after 6 loop-break attempts ──
                if state._loop_break_count >= 6:
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
                    state.status = SessionStatus.COMPLETED
                    yielded_terminal = True
                    yield AgentEvent("message", {"content": content, "usage": usage})
                    return

                # ── Dynamic tool selection + token budget partitioning ─────
                active_tools = self._select_tools(state)
                tools_json = self._registry.to_openai_tools_subset(active_tools)
                tool_tokens = sum(
                    len(json.dumps(t)) // 4 + 4 for t in tools_json
                )
                system_tokens = sum(
                    _estimate_message_tokens(m)
                    for m in state.memory._messages
                    if m.get("role") == "system"
                )
                completion_reserve = self._settings.llm_max_tokens
                fixed_overhead = system_tokens + tool_tokens + completion_reserve
                context_window = self._settings.llm_model_context_window
                history_budget = max(context_window - fixed_overhead, 4000)
                state.memory.set_history_budget(history_budget)

                logger.info(
                    "llm_call_start",
                    session_id=state.session_id,
                    step=state.step_count,
                    message_count=state.memory.message_count,
                    history_budget=history_budget,
                    context_window=context_window,
                )

                response: LLMResponse | None = None
                streamed = False
                try:
                    llm_progress_tick = 0
                    empty_ticks = 0
                    stream_iter = self._stream_llm_call(
                        state, tools_json
                    ).__aiter__()
                    get_next: asyncio.Future[AgentEvent | LLMResponse] | None = None

                    async with asyncio.timeout(llm_timeout):
                        while True:
                            if get_next is None:
                                get_next = asyncio.ensure_future(stream_iter.__anext__())
                            done, _ = await asyncio.wait(
                                {get_next}, timeout=_PROGRESS_INTERVAL
                            )
                            if not done:
                                llm_progress_tick += 1
                                empty_ticks += 1
                                if empty_ticks >= _CHUNK_DEAD_TICKS:
                                    logger.error(
                                        "llm_stream_dead",
                                        session_id=state.session_id,
                                        silent_seconds=empty_ticks * _PROGRESS_INTERVAL,
                                    )
                                    get_next.cancel()
                                    raise TimeoutError(
                                        f"LLM stream dead — no data for "
                                        f"{empty_ticks * _PROGRESS_INTERVAL}s"
                                    )
                                hint = _LLM_THINKING_MESSAGES[
                                    min(llm_progress_tick - 1, len(_LLM_THINKING_MESSAGES) - 1)
                                ]
                                yield AgentEvent("progress", {
                                    "tool": "thinking",
                                    "elapsed_seconds": llm_progress_tick * _PROGRESS_INTERVAL,
                                    "message": hint,
                                })
                                continue

                            empty_ticks = 0
                            try:
                                item = get_next.result()
                            except StopAsyncIteration:
                                break
                            finally:
                                get_next = None

                            if isinstance(item, LLMResponse):
                                response = item
                            elif item.event_type == "heartbeat":
                                pass
                            else:
                                yield item
                    streamed = True
                except TimeoutError:
                    consecutive_llm_timeouts += 1
                    logger.error(
                        "llm_timeout",
                        session_id=state.session_id,
                        step=state.step_count,
                        consecutive=consecutive_llm_timeouts,
                    )
                    if consecutive_llm_timeouts >= max_consecutive_llm_timeouts:
                        state.memory.add_assistant(
                            content=(
                                "I'm having trouble generating a response for this "
                                "request — it keeps timing out. This usually happens "
                                "with very complex requests. Please try breaking it "
                                "into smaller steps, or rephrase to be more specific."
                            ),
                        )
                        state.status = SessionStatus.COMPLETED
                        yielded_terminal = True
                        yield AgentEvent("message", {
                            "content": (
                                "I'm having trouble generating a response for this "
                                "request — it keeps timing out. This usually happens "
                                "with very complex requests. Please try breaking it "
                                "into smaller steps, or rephrase to be more specific."
                            ),
                        })
                        return
                    yield AgentEvent("error_recovery", {
                        "tool": "llm",
                        "error": "The AI model is taking longer than expected. Retrying...",
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
                                tools=tools_json,
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
                            "error": "The AI model took too long to respond. The conversation may be too large — consider starting a new chat.",
                        })
                        continue
                    except Exception as fallback_exc:
                        logger.error(
                            "llm_fallback_failed",
                            session_id=state.session_id,
                            error=str(fallback_exc),
                        )
                        yield AgentEvent("error_recovery", {
                            "tool": "llm",
                            "error": str(fallback_exc),
                            "cause": "LLM rejected the request after both stream and non-stream attempts.",
                            "hint": "Check your API key and model settings. If using DeepSeek or OpenAI, verify your key is valid. If using Ollama, ensure it is running locally.",
                        })
                        state.status = SessionStatus.ERROR
                        yielded_terminal = True
                        yield AgentEvent("message", {
                            "content": "The AI model is not responding. Check your API key and model settings, then try again.",
                        })
                        return

                if response is None:
                    yield AgentEvent("error_recovery", {
                        "tool": "llm",
                        "error": "The AI model returned no response. Retrying with a simpler approach.",
                    })
                    continue

                consecutive_llm_timeouts = 0

                if state._generation != my_generation:
                    return

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

                u = response.usage or {}
                p_tok = u.get("prompt_tokens", 0)
                c_tok = u.get("completion_tokens", 0)
                if p_tok == 0 and c_tok == 0:
                    p_tok = sum(
                        len(str(m.get("content", ""))) // 4
                        for m in state.memory.messages
                    )
                    c_tok = (
                        len(response.content or "") +
                        len(response.reasoning_content or "") +
                        sum(len(json.dumps(tc.arguments)) for tc in response.tool_calls)
                    ) // 4
                state._total_prompt_tokens += p_tok
                state._total_completion_tokens += c_tok
                state._total_cost += _estimate_step_cost(
                    self._llm._effective_model(), p_tok, c_tok,
                )
                yield AgentEvent("usage", {
                    "prompt_tokens": state._total_prompt_tokens,
                    "completion_tokens": state._total_completion_tokens,
                    "total_tokens": state._total_prompt_tokens + state._total_completion_tokens,
                    "estimated_cost": round(state._total_cost, 6),
                })

                if not response.has_tool_calls:
                    content = (response.content or "").strip()
                    if not content and state._empty_response_retries < 2:
                        state._empty_response_retries += 1
                        logger.warning(
                            "empty_llm_response",
                            session_id=state.session_id,
                            step=state.step_count,
                            retry=state._empty_response_retries,
                            finish_reason=response.finish_reason,
                        )
                        state.memory.add_user(
                            "Your previous response was empty. Please respond with "
                            "either a message summarizing progress or a tool call "
                            "to continue work."
                        )
                        yield AgentEvent("error_recovery", {
                            "error": "The model returned an empty response. Retrying...",
                        })
                        continue
                    state._empty_response_retries = 0
                    state.memory.add_assistant(
                        content=response.content,
                        reasoning_content=response.reasoning_content,
                        raw_message=response.raw_message,
                    )
                    state.status = SessionStatus.COMPLETED
                    yielded_terminal = True
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
                deferred_user_msgs: list[str] = []
                deferred_events: list[AgentEvent] = []
                early_return = False

                # ── Parallel fast-path for independent read-only tools ────
                can_parallel = (
                    len(response.tool_calls) > 1
                    and all(tc.name in _PARALLELIZABLE_TOOLS for tc in response.tool_calls)
                    and not any(self._requires_unapproved_apply_gate(tc, state) for tc in response.tool_calls)
                )
                if can_parallel:
                    session_vault = self._secret_vault.for_session(state.session_id)
                    parallel_tasks: dict[str, asyncio.Task[ToolResult]] = {}
                    gated_ids: set[str] = set()
                    for tc in response.tool_calls:
                        state.record_tool_call(tc.name, tc.arguments)
                        logger.info(
                            "tool_call_parallel",
                            session_id=state.session_id,
                            step=state.step_count,
                            tool=tc.name,
                            tool_call_id=tc.id,
                        )
                        yield AgentEvent("tool_call", session_vault.redact_dict({
                            "tool": tc.name,
                            "arguments": tc.arguments,
                            "tool_call_id": tc.id,
                        }))

                        gate_block = self._check_search_gate(state, tc.name)
                        if gate_block:
                            logger.warning(
                                "search_gate_blocked",
                                tool=tc.name,
                                exec_fail_count=state._exec_fail_count,
                            )
                            state.memory.add_tool_result(tc.id, gate_block.model_dump_json())
                            yield AgentEvent("tool_result", session_vault.redact_dict({
                                "tool": tc.name,
                                "tool_call_id": tc.id,
                                "status": gate_block.status.value,
                                "output": gate_block.error or "",
                            }))
                            gated_ids.add(tc.id)
                            continue

                        ptask = asyncio.create_task(
                            self._execute_tool(state, tc.name, tc.arguments)
                        )
                        state.track_task(ptask)
                        parallel_tasks[tc.id] = ptask

                    progress_tick = 0
                    pending = set(parallel_tasks.values())
                    tool_names = ", ".join(tc.name for tc in response.tool_calls)
                    while pending:
                        done_set, pending = await asyncio.wait(pending, timeout=_PROGRESS_INTERVAL)
                        if not done_set:
                            if state._generation != my_generation:
                                for p in pending:
                                    p.cancel()
                                return
                            progress_tick += 1
                            elapsed = progress_tick * _PROGRESS_INTERVAL
                            elapsed_str = f"{elapsed // 60}m {elapsed % 60}s" if elapsed >= 60 else f"{elapsed}s"
                            yield AgentEvent("progress", {
                                "tool": "parallel",
                                "elapsed_seconds": elapsed,
                                "message": f"[{elapsed_str}] Running {len(pending)} tools in parallel ({tool_names})...",
                            })

                    deferred_user_msgs_p: list[str] = []
                    deferred_events_p: list[AgentEvent] = []
                    for tc in response.tool_calls:
                        if tc.id in gated_ids:
                            continue
                        result = parallel_tasks[tc.id].result()
                        last_activity_mono = _time.monotonic()
                        _stall_warned = False
                        try:
                            state.memory.add_tool_result(tc.id, result.model_dump_json())
                        except Exception:
                            state.memory.add_tool_result(
                                tc.id,
                                f'{{"status":"{result.status.value}","output":"{result.output[:500]}"}}'
                            )
                        tool_result_payload: dict[str, Any] = {
                            "tool": tc.name,
                            "tool_call_id": tc.id,
                            "status": result.status.value,
                            "output": result.output[:2000],
                        }
                        if result.data:
                            tool_result_payload["data"] = result.data
                        yield AgentEvent("tool_result", session_vault.redact_dict(tool_result_payload))
                        with contextlib.suppress(Exception):
                            await infra_tracker.update_infrastructure(
                                tc.name, result, state.session_id,
                            )
                        if tc.name == "web_search" and result.status != ToolStatus.ERROR:
                            state._searched_since_exec_fail = True

                        if result.status == ToolStatus.ERROR:
                            # Auto-remediation: detect missing Python SDK and install it
                            if tc.name in self._EXECUTION_TOOLS:
                                from ansible_forge.dep_manager import (
                                    ensure_packages,
                                    guess_pip_package,
                                    parse_missing_module,
                                )

                                _missing = parse_missing_module(result.error or "")
                                if not _missing and result.data:
                                    _missing = parse_missing_module(
                                        str(result.data.get("raw_stdout", ""))
                                    )
                                if _missing:
                                    _pkg = guess_pip_package(_missing)
                                    _ok, _msg = await ensure_packages(
                                        [_pkg], reason=f"auto-fix for {tc.name}"
                                    )
                                    if _ok:
                                        deferred_user_msgs_p.append(
                                            f"Missing Python package '{_pkg}' was auto-installed. "
                                            f"Retry the same action now."
                                        )
                                        deferred_events_p.append(AgentEvent("progress", {
                                            "tool": "dep_manager",
                                            "message": f"Auto-installed {_pkg}",
                                        }))
                                        continue

                            state._consecutive_errors += 1
                            state.last_error = result.error
                            if tc.name in self._EXECUTION_TOOLS:
                                state._exec_fail_count += 1
                            remaining = max(state._max_error_retries - state._consecutive_errors, 0)

                            if remaining <= 0:
                                deferred_user_msgs_p.append(
                                    "You have exhausted all error retries. STOP trying the same "
                                    "approach. Summarize exactly what went wrong, what you tried, "
                                    "and ask the user for guidance on how to proceed."
                                )
                                deferred_events_p.append(AgentEvent("error_recovery", {
                                    "tool": tc.name,
                                    "error": result.error,
                                    "retries_remaining": 0,
                                    "budget_exhausted": True,
                                }))
                            else:
                                error_ctx = ERROR_RECOVERY_PROMPT.format(
                                    tool_name=tc.name,
                                    error_message=result.error or "Unknown error",
                                    remaining_retries=remaining,
                                )
                                exec_directive = self._build_exec_fail_directive(
                                    tc.name, result.error or "",
                                    state._exec_fail_count,
                                    state._searched_since_exec_fail,
                                )
                                if exec_directive:
                                    error_ctx += f"\n\n{exec_directive}"
                                deferred_user_msgs_p.append(error_ctx)
                                deferred_events_p.append(AgentEvent("error_recovery", {
                                    "tool": tc.name,
                                    "error": result.error,
                                    "retries_remaining": remaining,
                                }))
                        else:
                            state._consecutive_errors = 0
                            if tc.name in self._EXECUTION_TOOLS and result.status == ToolStatus.SUCCESS:
                                state._exec_fail_count = 0
                                state._searched_since_exec_fail = False

                    for msg in deferred_user_msgs_p:
                        state.memory.add_user(msg)
                    for evt in deferred_events_p:
                        yield evt

                    logger.info(
                        "parallel_tools_complete",
                        session_id=state.session_id,
                        tool_count=len(response.tool_calls),
                        step=state.step_count,
                    )
                    continue

                # ── Sequential path (approval gates, secrets, side effects) ──
                for tc in response.tool_calls:
                    state.record_tool_call(tc.name, tc.arguments)

                    pattern = state.loop_pattern
                    if not pattern and state.has_repeated_errors():
                        pattern = "error_identical"
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
                        is_hard_loop = pattern in ("exact_repeat", "alternating", "error_identical")
                        if is_hard_loop:
                            remaining_idx = response.tool_calls.index(tc)
                            for remaining_tc in response.tool_calls[remaining_idx:]:
                                state.memory.add_tool_result(
                                    remaining_tc.id,
                                    '{"status":"error","output":"Tool call skipped — identical call loop detected."}',
                                )
                            deferred_user_msgs.append(LOOP_BREAK_PROMPT)
                            deferred_events.append(AgentEvent("error_recovery", {
                                "tool": tc.name,
                                "error": "The agent appears to be stuck repeating the same action. Pausing to reassess.",
                            }))
                            loop_broken = True
                            break
                        deferred_user_msgs.append(LOOP_BREAK_PROMPT)
                        deferred_events.append(AgentEvent("error_recovery", {
                            "tool": tc.name,
                            "error": "The agent has been running the same type of action many times — checking if this is intentional.",
                        }))

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

                    if self._requires_unapproved_apply_gate(tc, state):
                        playbook_name = tc.arguments.get("playbook", "unknown")
                        state.status = SessionStatus.AWAITING_APPROVAL
                        gate_msg = (
                            f"Apply mode requested for '{playbook_name}' without a prior "
                            f"dry-run approval. Approval is required before live execution."
                        )
                        yield AgentEvent("approval_required", {
                            "session_id": state.session_id,
                            "output": gate_msg,
                            "data": {"playbook": playbook_name, "mode": "apply"},
                        })
                        approval = self._approval_gate.create_request(
                            session_id=state.session_id,
                            description=f"Apply {playbook_name} (no prior dry-run)",
                            diff_summary=gate_msg,
                            metadata={"playbook": playbook_name, "mode": "apply"},
                        )
                        gate_status = await approval.wait(timeout=600)
                        if state._generation != my_generation:
                            return
                        if gate_status == ApprovalStatus.APPROVED:
                            state.status = SessionStatus.ACTIVE
                            state._approved_playbooks.add(playbook_name)
                            yield AgentEvent("approval_granted", {
                                "session_id": state.session_id,
                            })
                        else:
                            state.status = SessionStatus.REJECTED
                            feedback = approval.feedback or "User rejected apply without dry-run."
                            state.memory.add_tool_result(
                                tc.id,
                                f'{{"status":"error","output":"Rejected: {feedback}"}}',
                            )
                            state.memory.add_user(f"User rejected: {feedback}")
                            yield AgentEvent("approval_rejected", {
                                "session_id": state.session_id,
                                "feedback": feedback,
                            })
                            early_return = True
                            break

                    if is_file_writing_tool(tc.name):
                        try:
                            await create_checkpoint(
                                state.workspace.path,
                                f"before {tc.name}",
                                step=state.step_count,
                            )
                        except Exception:
                            logger.debug("checkpoint_before_failed", tool=tc.name, exc_info=True)

                    gate_block = self._check_search_gate(state, tc.name)
                    if gate_block:
                        logger.warning(
                            "search_gate_blocked",
                            tool=tc.name,
                            exec_fail_count=state._exec_fail_count,
                        )
                        state.memory.add_tool_result(tc.id, gate_block.model_dump_json())
                        result = gate_block
                        yield AgentEvent("tool_result", session_vault.redact_dict({
                            "tool": tc.name,
                            "tool_call_id": tc.id,
                            "status": result.status.value,
                            "output": result.output or result.error or "",
                        }))
                        deferred_user_msgs.append(
                            f"`{tc.name}` was BLOCKED because you have not searched "
                            f"for the error after {state._exec_fail_count} failures. "
                            f"Call `web_search` with the error message, then retry."
                        )
                        continue

                    _tool_timeout = tc.arguments.get("timeout", 0) or 0
                    _is_long_tool = (
                        tc.name in ("execute_playbook", "run_adhoc", "terraform_exec")
                        and _tool_timeout > 60
                    ) or tc.name == "terraform_exec"
                    if _is_long_tool and not (response.content and response.content.strip()):
                        _tool_label = tc.name
                        _tool_detail = ""
                        if tc.name == "run_adhoc":
                            _mod_args = tc.arguments.get("module_args", "")
                            _tool_detail = f" ({_mod_args[:80]})" if _mod_args else ""
                        elif tc.name == "execute_playbook":
                            _tool_detail = f" ({tc.arguments.get('playbook', '')})"
                        elif tc.name == "terraform_exec":
                            _tool_detail = f" ({tc.arguments.get('action', '')})"
                        _timeout_hint = ""
                        if _tool_timeout > 0:
                            _tm = int(_tool_timeout)
                            _timeout_hint = (
                                f" (timeout: {_tm // 60}m)"
                                if _tm >= 60
                                else f" (timeout: {_tm}s)"
                            )
                        yield AgentEvent("progress", {
                            "tool": tc.name,
                            "elapsed_seconds": 0,
                            "step": state.step_count,
                            "message": (
                                f"Starting {_tool_label}{_tool_detail}{_timeout_hint} "
                                f"— the UI will stream output as it arrives."
                            ),
                        })

                    live_queue: asyncio.Queue[dict[str, Any]] | None = None
                    if tc.name in ("execute_playbook", "run_adhoc", "local_exec", "terraform_exec"):
                        live_queue = asyncio.Queue()
                        tc.arguments["_live_log_queue"] = live_queue

                    pending_run_id: int | None = None
                    if tc.name in ("execute_playbook", "run_adhoc", "terraform_exec"):
                        try:
                            from ansible_forge.persistence.infrastructure_store import (
                                InfrastructureStore,
                            )
                            _store = InfrastructureStore.get_instance()
                            _run_label = tc.arguments.get("playbook", tc.arguments.get("module", "unknown"))
                            if tc.name == "terraform_exec":
                                _run_label = f"terraform {tc.arguments.get('action', 'unknown')}"
                            elif tc.name == "run_adhoc":
                                _args = tc.arguments.get("module_args", "")
                                _run_label = f"adhoc: {(_args[:80] if _args else tc.arguments.get('module', 'shell'))}"
                            _loop = asyncio.get_running_loop()
                            _run_mode = tc.arguments.get("mode", tc.arguments.get("action", "run"))
                            _sid = state.session_id
                            pending_run_id = await _loop.run_in_executor(
                                None,
                                partial(
                                    _store.record_run,
                                    session_id=_sid,
                                    playbook=_run_label,
                                    mode=_run_mode,
                                    hosts=[],
                                    status="running",
                                ),
                            )
                        except Exception:
                            logger.debug("pending_run_record_failed", tool=tc.name, exc_info=True)

                    task = asyncio.create_task(
                        self._execute_tool(state, tc.name, tc.arguments)
                    )
                    state.track_task(task)
                    progress_tick = 0
                    total_elapsed = 0.0
                    last_progress_at = 0.0
                    msgs = _TOOL_PROGRESS_MESSAGES.get(tc.name, _DEFAULT_PROGRESS_MESSAGES)

                    _tool_ctx_label = ""
                    if tc.name == "run_adhoc":
                        _ma = tc.arguments.get("module_args", "")
                        _mod = tc.arguments.get("module", "shell")
                        _tool_ctx_label = f" [{_mod}: {_ma[:60]}]" if _ma else f" [{_mod}]"
                    elif tc.name == "execute_playbook":
                        _pb = tc.arguments.get("playbook", "")
                        _tool_ctx_label = f" [{_pb}]" if _pb else ""
                    elif tc.name == "terraform_exec":
                        _act = tc.arguments.get("action", "")
                        _tool_ctx_label = f" [terraform {_act}]" if _act else ""
                    elif tc.name == "local_exec":
                        _cmd = tc.arguments.get("command", "")
                        _tool_ctx_label = f" [{_cmd[:60]}]" if _cmd else ""

                    _timeout_for_display = tc.arguments.get("timeout", 0) or 0

                    while not task.done():
                        poll = 1.0 if live_queue else (
                            _PROGRESS_INTERVAL if total_elapsed < 60 else 15
                        )
                        done, _ = await asyncio.wait({task}, timeout=poll)

                        if live_queue:
                            while not live_queue.empty():
                                try:
                                    yield AgentEvent("live_log", live_queue.get_nowait())
                                except asyncio.QueueEmpty:
                                    break

                        if done:
                            break
                        if state._generation != my_generation:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            logger.info(
                                "tool_cancelled_on_supersession",
                                session_id=state.session_id,
                                tool=tc.name,
                            )
                            return

                        total_elapsed += poll
                        progress_interval = (
                            _PROGRESS_INTERVAL if total_elapsed < 60 else 15
                        )
                        if total_elapsed - last_progress_at >= progress_interval:
                            last_progress_at = total_elapsed
                            progress_tick += 1
                            elapsed = int(total_elapsed)
                            hint = msgs[min(progress_tick - 1, len(msgs) - 1)]
                            elapsed_str = (
                                f"{elapsed // 60}m {elapsed % 60}s"
                                if elapsed >= 60
                                else f"{elapsed}s"
                            )
                            timeout_part = ""
                            if _timeout_for_display > 0:
                                _tmin = int(_timeout_for_display) // 60
                                timeout_part = f" | timeout: {_tmin}m" if _tmin > 0 else ""
                            yield AgentEvent("progress", {
                                "tool": tc.name,
                                "elapsed_seconds": elapsed,
                                "step": state.step_count,
                                "message": f"[{elapsed_str}{timeout_part}]{_tool_ctx_label} {hint}",
                            })

                    if live_queue:
                        while not live_queue.empty():
                            try:
                                yield AgentEvent("live_log", live_queue.get_nowait())
                            except asyncio.QueueEmpty:
                                break

                    if task.cancelled():
                        return
                    result = task.result()

                    if is_file_writing_tool(tc.name) and result.status != ToolStatus.ERROR:
                        try:
                            cp_hash = await create_checkpoint(
                                state.workspace.path,
                                f"after {tc.name}: {tc.arguments.get('playbook', tc.arguments.get('path', tc.name))}",
                                step=state.step_count,
                            )
                            if cp_hash:
                                yield AgentEvent("checkpoint", {
                                    "hash": cp_hash,
                                    "tool": tc.name,
                                    "step": state.step_count,
                                })
                        except Exception:
                            logger.debug("checkpoint_after_failed", tool=tc.name, exc_info=True)

                    if state._generation != my_generation:
                        return

                    logger.info(
                        "tool_result",
                        session_id=state.session_id,
                        step=state.step_count,
                        tool=tc.name,
                        tool_call_id=tc.id,
                        status=result.status.value,
                        output_preview=session_vault.redact(result.output[:500]) if result.output else "",
                    )

                    if (
                        result.status == ToolStatus.NEEDS_APPROVAL
                        and result.data.get("secret_request")
                    ):
                        secret_name = result.data["secret_name"]
                        secret_desc = result.data["secret_description"]
                        sensitive_type = result.data.get("sensitive_type", "other")
                        state.status = SessionStatus.AWAITING_SECRET

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
                            state.status = SessionStatus.ACTIVE
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

                        if state._generation != my_generation:
                            return

                        stored_value = session_vault.get(secret_name)
                        if stored_value is None:
                            state.status = SessionStatus.ACTIVE
                            cancel_msg = (
                                f"Secret '{secret_name}' request was cancelled. "
                                "The user may have interrupted. Ask them what they'd prefer."
                            )
                            state.memory.add_tool_result(tc.id, cancel_msg)
                            yield AgentEvent("tool_result", {
                                "tool": tc.name,
                                "tool_call_id": tc.id,
                                "status": "error",
                                "output": cancel_msg,
                            })
                            continue

                        state.status = SessionStatus.ACTIVE
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

                    last_activity_mono = _time.monotonic()
                    _stall_warned = False
                    try:
                        state.memory.add_tool_result(tc.id, result.model_dump_json())
                    except Exception:
                        state.memory.add_tool_result(
                            tc.id,
                            f'{{"status":"{result.status.value}","output":"{result.output[:500]}"}}'
                        )
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
                    with contextlib.suppress(Exception):
                        await infra_tracker.update_infrastructure(
                            tc.name, result, state.session_id, pending_run_id,
                        )

                    if result.status == ToolStatus.NEEDS_APPROVAL:
                        auto_approved = False
                        gate_status: ApprovalStatus | None = None
                        if tc.name == "execute_playbook" and self._is_localhost_only_playbook(tc, state):
                            auto_approved = True
                            pb = tc.arguments.get("playbook", "")
                            if pb:
                                state._approved_playbooks.add(pb)
                            yield AgentEvent("approval_granted", {"session_id": state.session_id})

                        if not auto_approved:
                            state.status = SessionStatus.AWAITING_APPROVAL
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

                            gate_status = await approval.wait(timeout=600)
                            if state._generation != my_generation:
                                return

                        if auto_approved or gate_status == ApprovalStatus.APPROVED:
                            state.status = SessionStatus.ACTIVE
                            if tc.name == "execute_playbook":
                                pb = tc.arguments.get("playbook", "")
                                if pb:
                                    state._approved_playbooks.add(pb)
                            if not auto_approved:
                                yield AgentEvent("approval_granted", {"session_id": state.session_id})
                            if state._rejected_output and state._rejected_tool == tc.name:
                                state._rejected_output = None
                                state._rejected_feedback = None
                                state._rejected_tool = None
                        else:
                            state.status = SessionStatus.REJECTED
                            feedback = approval.feedback or "User rejected the operation."
                            state._rejected_output = result.output[:2000]
                            state._rejected_feedback = feedback
                            state._rejected_tool = tc.name
                            remaining_idx = response.tool_calls.index(tc) + 1
                            for remaining_tc in response.tool_calls[remaining_idx:]:
                                state.memory.add_tool_result(
                                    remaining_tc.id,
                                    '{"status":"error","output":"Skipped — prior tool was rejected."}',
                                )
                            state.memory.add_user(f"User rejected: {feedback}")
                            yield AgentEvent("approval_rejected", {
                                "session_id": state.session_id,
                                "feedback": feedback,
                            })
                            early_return = True
                            break

                    if tc.name == "web_search" and result.status != ToolStatus.ERROR:
                        state._searched_since_exec_fail = True

                    if result.status == ToolStatus.ERROR:
                        # Auto-remediation: detect missing Python SDK and install it
                        _auto_fixed = False
                        if tc.name in self._EXECUTION_TOOLS:
                            from ansible_forge.dep_manager import (
                                ensure_packages,
                                guess_pip_package,
                                parse_missing_module,
                            )

                            _missing = parse_missing_module(result.error or "")
                            if not _missing and result.data:
                                _missing = parse_missing_module(
                                    str(result.data.get("raw_stdout", ""))
                                )
                            if _missing:
                                _pkg = guess_pip_package(_missing)
                                _ok, _msg = await ensure_packages(
                                    [_pkg], reason=f"auto-fix for {tc.name}"
                                )
                                if _ok:
                                    deferred_user_msgs.append(
                                        f"Missing Python package '{_pkg}' was auto-installed. "
                                        f"Retry the same action now."
                                    )
                                    deferred_events.append(AgentEvent("progress", {
                                        "tool": "dep_manager",
                                        "message": f"Auto-installed {_pkg}",
                                    }))
                                    _auto_fixed = True

                        if not _auto_fixed:
                            state._consecutive_errors += 1
                            state.last_error = result.error
                            state._last_error_by_tool[tc.name] = {
                                "error": result.error or "Unknown error",
                                "args": {k: v for k, v in tc.arguments.items() if k != "_session_id"},
                            }
                            if tc.name in self._EXECUTION_TOOLS:
                                state._exec_fail_count += 1
                            remaining = max(state._max_error_retries - state._consecutive_errors, 0)

                            if remaining <= 0:
                                deferred_user_msgs.append(
                                    "You have exhausted all error retries. STOP trying the same "
                                    "approach. Summarize exactly what went wrong, what you tried, "
                                    "and ask the user for guidance on how to proceed."
                                )
                                deferred_events.append(AgentEvent("error_recovery", {
                                    "tool": tc.name,
                                    "error": result.error,
                                    "retries_remaining": 0,
                                    "budget_exhausted": True,
                                }))
                            else:
                                error_ctx = ERROR_RECOVERY_PROMPT.format(
                                    tool_name=tc.name,
                                    error_message=result.error or "Unknown error",
                                    remaining_retries=remaining,
                                )
                                exec_directive = self._build_exec_fail_directive(
                                    tc.name, result.error or "",
                                    state._exec_fail_count,
                                    state._searched_since_exec_fail,
                                )
                                if exec_directive:
                                    error_ctx += f"\n\n{exec_directive}"
                                deferred_user_msgs.append(error_ctx)
                                deferred_events.append(AgentEvent("error_recovery", {
                                    "tool": tc.name,
                                    "error": result.error,
                                    "retries_remaining": remaining,
                                }))
                    else:
                        state._consecutive_errors = 0
                        if tc.name in self._EXECUTION_TOOLS and result.status == ToolStatus.SUCCESS:
                            state._exec_fail_count = 0
                            state._searched_since_exec_fail = False

                    if (
                        tc.name == "execute_playbook"
                        and result.status == ToolStatus.SUCCESS
                        and result.data.get("mode") == "apply"
                    ):
                        deferred_user_msgs.append(
                            "The playbook was applied successfully. Now VERIFY the changes "
                            "actually took effect. Use the `verify_state` tool to check that "
                            "services are running, ports are listening, or endpoints are reachable. "
                            "Do NOT just report success — prove it with evidence."
                        )

                    if tc.name == "verify_state" and result.status == ToolStatus.ERROR:
                        failed_checks = result.data.get("failed", 0)
                        deferred_user_msgs.append(
                            f"Verification FAILED ({failed_checks} checks). "
                            "Consider generating a rollback playbook with `generate_rollback` "
                            "for the most recently applied playbook, then present the rollback "
                            "plan to the user for approval before executing it."
                        )

                if early_return:
                    state.status = SessionStatus.REJECTED
                    yielded_terminal = True
                    yield AgentEvent("message", {
                        "content": (
                            "The requested action was not approved and has been cancelled. "
                            "Let me know how you'd like to proceed."
                        ),
                    })
                    return

                for msg in deferred_user_msgs:
                    state.memory.add_user(msg)
                for evt in deferred_events:
                    yield evt

                if loop_broken:
                    continue

            except asyncio.CancelledError:
                raise
            except Exception as step_exc:
                logger.error(
                    "react_step_failed",
                    session_id=state.session_id,
                    step=state.step_count,
                    error=str(step_exc),
                    exc_info=True,
                )
                state.memory.add_user(
                    f"Internal error during step {state.step_count}: {step_exc}. "
                    "Retry or adjust your approach."
                )
                yield AgentEvent("error_recovery", {
                    "error": str(step_exc),
                    "step": state.step_count,
                })
                continue

          state.status = SessionStatus.MAX_STEPS_REACHED
          yielded_terminal = True
          yield AgentEvent("max_steps", {
              "step_count": state.step_count,
              "message": f"The agent has completed {max_steps} steps — the maximum allowed. You can continue the conversation to pick up where it left off.",
          })
        finally:
            if not yielded_terminal and state._generation == my_generation:
                state.status = SessionStatus.COMPLETED
                yield AgentEvent("message", {
                    "content": (
                        "The agent stopped unexpectedly. "
                        "You can send a new message to continue."
                    ),
                })

    async def _stream_llm_call(
        self,
        state: SessionState,
        tools: list[dict[str, Any]] | None,
    ) -> AsyncIterator[AgentEvent | LLMResponse]:
        """Stream an LLM call, yielding delta events for each token.

        Emits ``thinking_delta`` for reasoning tokens and tool-call preamble,
        ``message_delta`` for final-answer content (when no tool calls are
        being built).  The **last** item yielded is the accumulated ``LLMResponse``.
        """
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tc_accum: dict[int, dict[str, Any]] = {}
        finish_reason: str | None = None
        usage: dict[str, int] | None = None
        saw_tool_call = False

        async for chunk in self._llm.complete_stream(
            messages=state.memory.messages,
            tools=tools,
        ):
            if chunk.get("heartbeat"):
                yield AgentEvent("heartbeat", {})
                continue

            if chunk.get("tool_calls"):
                saw_tool_call = True
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

            if chunk.get("reasoning_content"):
                reasoning_parts.append(chunk["reasoning_content"])
                yield AgentEvent("thinking_delta", {"content": chunk["reasoning_content"]})

            if chunk.get("content"):
                content_parts.append(chunk["content"])
                event_type = "thinking_delta" if saw_tool_call else "message_delta"
                yield AgentEvent(event_type, {"content": chunk["content"]})

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

    _PLAN_PROMPT = (
        "Before executing, create a brief plan. Respond ONLY with a JSON object:\n"
        '{"steps": [{"step": 1, "action": "...", "tool": "tool_name"}, ...]}\n'
        "Keep it to 3-8 steps. If the request is simple (e.g. a question, "
        "explanation, or single tool call), respond with: {\"steps\": []}\n"
        "Do NOT call any tools. Just output the JSON plan."
    )

    async def _generate_plan(
        self, state: SessionState, user_message: str
    ) -> dict[str, Any] | None:
        if state.step_count > 0:
            return None

        try:
            context_parts = [user_message[:1000]]
            _loop = asyncio.get_running_loop()
            ws_context = await _loop.run_in_executor(
                None, build_context, state.workspace
            )
            if ws_context:
                context_parts.append(f"\nWorkspace:\n{ws_context[:500]}")
            plan_input = "\n".join(context_parts)

            response = await asyncio.wait_for(
                self._llm.complete(
                    messages=[
                        {"role": "system", "content": self._PLAN_PROMPT},
                        {"role": "user", "content": plan_input},
                    ],
                    tools=None,
                    max_tokens=500,
                ),
                timeout=15,
            )
            if not response.content:
                return None

            text = response.content.strip()
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                plan_data = json.loads(text[start:end])
                steps = plan_data.get("steps", [])
                if steps:
                    logger.info(
                        "plan_generated",
                        session_id=state.session_id,
                        step_count=len(steps),
                    )
                    plan_data_full = {"steps": steps, "status": "planned"}
                    state.plan = plan_data_full
                    return plan_data_full
        except (TimeoutError, json.JSONDecodeError, Exception):
            logger.debug("plan_generation_skipped", exc_info=True)
        return None

    async def _execute_tool(
        self, state: SessionState, tool_name: str, arguments: dict[str, Any]
    ) -> ToolResult:
        """Execute a tool, injecting workspace_path and session_id where needed."""
        tool = self._registry.get(tool_name)
        if tool is None:
            return ToolResult.fail(f"Unknown tool: {tool_name}")

        tool_props = tool.parameters.get("properties", {})
        if "workspace_path" in tool_props:
            arguments["workspace_path"] = str(state.workspace.path)

        arguments["_session_id"] = state.session_id
        arguments["_workspace_path"] = str(state.workspace.path)
        arguments["_exec_fail_count"] = state._exec_fail_count

        if tool_name == "execute_playbook":
            result = self._pre_validate_playbook(arguments)
            if result is not None:
                return result

        try:
            result = await self._registry.execute(tool_name, arguments)
        except Exception as exc:
            logger.error("tool_execution_error", tool=tool_name, error=str(exc))
            result = ToolResult.fail(f"Tool execution failed: {exc}")

        if tool_name == "execute_playbook" and result.data.get("events"):
            report = self._diff_analyzer.analyze(result.data["events"])
            if report.has_changes:
                result.data["diff_summary"] = report.to_dict()

        return result

    def _pre_validate_playbook(self, arguments: dict[str, Any]) -> ToolResult | None:
        ws = arguments.get("workspace_path", "")
        pb = arguments.get("playbook", "")
        if not ws or not pb:
            return None
        vr = self._validator.validate(ws, pb)
        if not vr.passed:
            issues_str = "; ".join(
                f"[{i.severity}] {i.message}" for i in vr.issues
            )
            logger.warning(
                "playbook_validation_failed",
                playbook=pb,
                issues=vr.to_dict(),
            )
            return ToolResult.fail(
                f"Playbook validation blocked execution: {issues_str}",
                validation=vr.to_dict(),
            )
        if vr.warnings:
            logger.info(
                "playbook_validation_warnings",
                playbook=pb,
                warnings=[w.to_dict() for w in vr.warnings],
            )
        return None

    def store_secret(self, session_id: str, name: str, value: str, description: str = "") -> bool:
        """Store a secret in the session vault and unblock any pending request."""
        vault = self._secret_vault.for_session(session_id)
        vault.store(name, value, description)
        return True

    def list_secrets(self, session_id: str) -> list[dict[str, str]]:
        return self._secret_vault.for_session(session_id).list_names()

    def delete_secret(self, session_id: str, name: str) -> bool:
        return self._secret_vault.for_session(session_id).delete(name)

    @staticmethod
    def _is_localhost_only_playbook(tc: Any, state: SessionState) -> bool:
        """Return True if the playbook targets only localhost (safe to auto-approve)."""
        inv_path = tc.arguments.get("inventory", "")
        if not inv_path:
            return False
        try:
            from pathlib import Path

            import yaml

            inv_file = Path(inv_path)
            if not inv_file.exists():
                return False
            content = inv_file.read_text()
            if inv_file.suffix in (".yml", ".yaml"):
                data = yaml.safe_load(content) or {}
                hosts = set()
                for _, group_data in data.items():
                    if isinstance(group_data, dict):
                        group_hosts = group_data.get("hosts", {})
                        if isinstance(group_hosts, dict):
                            hosts.update(group_hosts.keys())
                return hosts and hosts <= {"localhost", "127.0.0.1"}
            if inv_file.suffix in (".ini", ""):
                return "localhost" in content and all(
                    line.strip().startswith("[")
                    or line.strip().startswith("#")
                    or line.strip() == ""
                    or "localhost" in line
                    or "127.0.0.1" in line
                    for line in content.splitlines()
                    if line.strip()
                )
        except Exception:
            logger.debug("localhost_check_failed", exc_info=True)
        return False

    @staticmethod
    def _requires_unapproved_apply_gate(tc: Any, state: SessionState) -> bool:
        """Return True if this tool call is a mutating execution that hasn't
        been through a prior approval in this session."""
        if tc.name == "execute_playbook":
            if tc.arguments.get("mode") != "apply":
                return False
            playbook = tc.arguments.get("playbook", "")
            if playbook in state._approved_playbooks:
                return False
            if Orchestrator._is_localhost_only_playbook(tc, state):
                state._approved_playbooks.add(playbook)
                return False
            return True

        if tc.name == "terraform_exec":
            action = tc.arguments.get("action", "")
            if action in ("apply", "destroy", "import"):
                return True

        return False

    def approve_session(self, session_id: str) -> bool:
        return self._approval_gate.approve(session_id)

    def reject_session(self, session_id: str, feedback: str = "") -> bool:
        return self._approval_gate.reject(session_id, feedback)

    def reset_session(self, session_id: str) -> None:
        """Clear in-memory agent state for a session while keeping its workspace."""
        state = self._sessions.get(session_id)
        if state is None:
            return
        ctx_limit = get_settings().llm_max_context_tokens
        state.memory = Memory(max_context_tokens=ctx_limit)
        state.memory.attach_vault(self._secret_vault.for_session(session_id))
        state.memory.add_system(self._build_system_prompt(state.workspace))
        state.step_count = 0
        state.status = SessionStatus.ACTIVE
        state.last_error = None
        state._recent_tool_calls.clear()
        state._progress_warned = False
        state._loop_break_count = 0
        state._consecutive_errors = 0
        state._exec_fail_count = 0
        state._searched_since_exec_fail = False
        state._total_prompt_tokens = 0
        state._total_completion_tokens = 0
        state._total_cost = 0.0
        state._generation += 1
        state.cancel_active_work()
        state._last_error_by_tool.clear()
        state._rejected_output = None
        state._rejected_feedback = None
        state._rejected_tool = None
        state._approved_playbooks.clear()
        state.plan = None
        self._approval_gate.cleanup(session_id)
        logger.info("session_reset", session_id=session_id)

    def destroy_session(self, session_id: str) -> None:
        state = self._sessions.get(session_id)
        if state:
            state.cancel_active_work()
        self._approval_gate.cleanup(session_id)
        self._secret_vault.destroy_session(session_id)
        self._workspace_mgr.destroy(session_id)
        self._sessions.pop(session_id, None)
        logger.info("session_destroyed", session_id=session_id)
