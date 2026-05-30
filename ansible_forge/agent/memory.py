"""Conversation and context memory for agent sessions."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ansible_forge.safety.secret_vault import SessionVault

_CHARS_PER_TOKEN = 4

logger = logging.getLogger(__name__)

_COMPACTION_PROMPT = (
    "You are a concise note-taker for an infrastructure automation session. "
    "Summarize the following conversation segment into a compact progress report. "
    "Focus on:\n"
    "1. Key DECISIONS made and WHY (e.g. 'chose us-east-1 because existing VPC is there')\n"
    "2. Infrastructure STATE changes (resources created/modified/destroyed with IDs/IPs)\n"
    "3. Errors encountered and HOW they were resolved\n"
    "4. Credentials/secrets COLLECTED — list EVERY secret name that was stored "
    "(the agent must NOT re-request these)\n"
    "5. Current deployment phase and what remains\n"
    "6. Research findings — key version numbers, prerequisites discovered, "
    "dependency chains, and compatibility constraints\n"
    "7. Playbooks/roles/files generated (filenames and purpose)\n\n"
    "Format as a bullet list. Be extremely concise — max 40 bullets. "
    "Omit tool call IDs, reasoning tokens, and verbose output. "
    "Preserve all hostnames, IPs, resource IDs, file paths, and config values."
)


def _estimate_message_tokens(msg: dict[str, Any]) -> int:
    """Fast heuristic token count for a single chat message."""
    total = 4  # role overhead
    content = msg.get("content") or ""
    if isinstance(content, str):
        total += len(content) // _CHARS_PER_TOKEN
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                total += len(str(part.get("text", ""))) // _CHARS_PER_TOKEN
    if "tool_calls" in msg:
        for tc in msg["tool_calls"]:
            fn = tc.get("function", {})
            total += len(fn.get("name", "")) // _CHARS_PER_TOKEN + 4
            args = fn.get("arguments", "")
            if isinstance(args, dict):
                args = json.dumps(args)
            total += len(args) // _CHARS_PER_TOKEN
    return total


class Memory:
    """Stores conversation history and tool results for a single session.

    Keeps messages in OpenAI chat format and prunes to stay within token budgets.
    Uses paired pruning to ensure tool_call messages always have their
    corresponding tool result messages (orphaned references break the LLM).

    When a ``SessionVault`` is attached, all incoming text is scrubbed so that
    raw secret values are replaced with ``<<SECRET:name>>`` placeholders before
    they ever enter the message list (and are therefore never sent to the LLM).
    """

    _JOURNAL_MAX_ENTRIES = 200
    _JOURNAL_ENTRY_MAX_CHARS = 200
    _COMPACTION_THRESHOLD_TOKENS = 32000
    _COMPACTION_KEEP_RECENT = 30

    def __init__(self, max_messages: int = 500, max_context_tokens: int = 0) -> None:
        self._messages: list[dict[str, Any]] = []
        self._max_messages = max_messages
        self._max_context_tokens = max_context_tokens
        self._dynamic_history_budget: int = 0
        self._metadata: dict[str, Any] = {}
        self._pinned_goal: str | None = None
        self._progress_journal: list[str] = []
        self.created_at = time.time()
        self._vault: SessionVault | None = None

    def attach_vault(self, vault: SessionVault) -> None:
        """Attach a session vault so that secrets are auto-redacted."""
        self._vault = vault

    def _redact(self, text: str) -> str:
        """Replace known secret values with placeholders."""
        if self._vault is None:
            return text
        return self._vault.redact(text)

    @property
    def messages(self) -> list[Any]:
        """Return messages for LLM consumption.

        Internal fields prefixed with ``_`` (like ``_raw_message``) are
        stripped.  ``reasoning_content`` is preserved only on the LAST
        assistant message — older reasoning is stripped to save tokens
        (thinking-mode models only need the most recent reasoning context).

        If older user messages have been pruned, a compact goal-reminder
        message is injected right after the system prompt so the LLM
        never loses track of the user's original request.
        """
        last_assistant_idx = -1
        for i in range(len(self._messages) - 1, -1, -1):
            if self._messages[i].get("role") == "assistant":
                last_assistant_idx = i
                break

        result: list[Any] = []
        context_injected = False
        for i, m in enumerate(self._messages):
            cleaned = {k: v for k, v in m.items() if not k.startswith("_")}
            if (
                m.get("role") == "assistant"
                and i != last_assistant_idx
                and "reasoning_content" in cleaned
            ):
                del cleaned["reasoning_content"]
            result.append(cleaned)
            if not context_injected and m.get("role") == "system":
                parts: list[str] = []
                if self._pinned_goal and self._goal_pruned():
                    parts.append(
                        f"[CONTEXT REMINDER — original user goal]\n{self._pinned_goal}"
                    )
                if self._progress_journal:
                    journal_text = "\n".join(self._progress_journal)
                    parts.append(
                        f"[PROGRESS LOG — actions from earlier steps, "
                        f"oldest first]\n{journal_text}"
                    )
                if parts:
                    result.append({
                        "role": "user",
                        "content": "\n\n".join(parts),
                    })
                    result.append({
                        "role": "assistant",
                        "content": (
                            "Understood — I have the original goal and "
                            "progress history in context."
                        ),
                    })
                context_injected = True
        return result

    def _goal_pruned(self) -> bool:
        """Check if the pinned goal's original message was pruned."""
        if not self._pinned_goal:
            return False
        for m in self._messages:
            if m.get("role") == "user":
                content = m.get("content", "")
                if isinstance(content, str) and self._pinned_goal[:80] in content:
                    return False
        return True

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_system(self, content: str) -> None:
        if self._messages and self._messages[0]["role"] == "system":
            self._messages[0]["content"] = content
        else:
            self._messages.insert(0, {"role": "system", "content": content})

    def add_user(self, content: str) -> None:
        redacted = self._redact(content)
        if self._pinned_goal is None and len(redacted.strip()) > 10:
            self._pinned_goal = redacted.strip()[:500]
        self._messages.append({"role": "user", "content": redacted})
        self._prune()

    def add_assistant(
        self,
        content: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        reasoning_content: str | None = None,
        raw_message: Any = None,
    ) -> None:
        msg: dict[str, Any] = {"role": "assistant", "content": content or ""}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        if reasoning_content is not None:
            msg["reasoning_content"] = reasoning_content
        if raw_message is not None:
            msg["_raw_message"] = raw_message
        self._messages.append(msg)
        self._prune()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": self._redact(content),
        })
        self._prune()

    def set_metadata(self, key: str, value: Any) -> None:
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self._metadata.get(key, default)

    def compress_old_tool_results(self, keep_recent: int = 20) -> int:
        """Truncate verbose tool results that are far from the conversation tail.

        Tool results older than *keep_recent* non-system messages keep only
        the JSON ``status`` field and the first 200 characters of ``output``.
        This preserves the conversation flow (what was called, pass/fail) while
        dramatically reducing token cost of stale context.

        Returns the number of messages compressed.
        """
        non_system = [m for m in self._messages if m.get("role") != "system"]
        if len(non_system) <= keep_recent:
            return 0

        cutoff_idx = len(non_system) - keep_recent
        old_msgs = set(id(m) for m in non_system[:cutoff_idx])
        compressed = 0

        for msg in self._messages:
            if id(msg) not in old_msgs or msg.get("role") != "tool":
                continue
            content = msg.get("content", "")
            if len(content) <= 300:
                continue
            try:
                parsed = json.loads(content)
                status = parsed.get("status", "unknown")
                output = parsed.get("output", "")
                summary = output[:200] + "..." if len(output) > 200 else output
                msg["content"] = json.dumps({"status": status, "output": summary})
                compressed += 1
            except (json.JSONDecodeError, AttributeError):
                if len(content) > 300:
                    msg["content"] = content[:200] + "...[truncated]"
                    compressed += 1
        return compressed

    async def compact_with_llm(self, llm_client: Any) -> bool:
        """Summarize old conversation turns using an LLM call.

        When total estimated tokens exceed ``_COMPACTION_THRESHOLD_TOKENS``,
        the older portion of the conversation (everything before the most
        recent ``_COMPACTION_KEEP_RECENT`` messages) is sent to the LLM for
        summarization.  The old messages are then replaced with a single
        compact digest message.

        Returns True if compaction was performed.
        """
        total_tokens = sum(_estimate_message_tokens(m) for m in self._messages)
        if total_tokens < self._COMPACTION_THRESHOLD_TOKENS:
            return False

        system_msgs = [m for m in self._messages if m.get("role") == "system"]
        other_msgs = [m for m in self._messages if m.get("role") != "system"]

        if len(other_msgs) <= self._COMPACTION_KEEP_RECENT:
            return False

        raw_split = len(other_msgs) - self._COMPACTION_KEEP_RECENT
        split = self._align_cut_to_tool_boundary(other_msgs, raw_split)
        old_block = other_msgs[:split]
        recent_block = other_msgs[split:]

        old_tokens = sum(_estimate_message_tokens(m) for m in old_block)
        if old_tokens < 2000:
            return False

        for m in old_block:
            self._journal_from_message(m)

        serialized = self._serialize_for_summary(old_block)

        try:
            response = await llm_client.complete(
                messages=[
                    {"role": "system", "content": _COMPACTION_PROMPT},
                    {"role": "user", "content": serialized},
                ],
                tools=None,
                max_tokens=1500,
                temperature=0.0,
            )
            summary = response.content or ""
        except Exception:
            logger.warning("compaction_llm_failed", exc_info=True)
            return False

        if not summary.strip():
            return False

        digest_msg = {
            "role": "user",
            "content": (
                f"[SESSION HISTORY — LLM-generated summary of "
                f"steps completed so far]\n{summary.strip()}"
            ),
        }
        ack_msg = {
            "role": "assistant",
            "content": "Understood — I have the session history summary in context.",
        }

        self._messages = system_msgs + [digest_msg, ack_msg] + recent_block
        logger.info(  # type: ignore[call-arg]
            "conversation_compacted",
            old_tokens=old_tokens,
            new_tokens=_estimate_message_tokens(digest_msg),
            remaining_messages=len(self._messages),
        )
        return True

    @staticmethod
    def _serialize_for_summary(messages: list[dict[str, Any]]) -> str:
        """Convert messages into a plain-text format for the summarizer."""
        lines: list[str] = []
        for m in messages:
            role = m.get("role", "?")
            if role == "assistant":
                tc = m.get("tool_calls")
                if tc:
                    tools = ", ".join(
                        t.get("function", {}).get("name", "?") for t in tc
                    )
                    lines.append(f"ASSISTANT: [called {tools}]")
                content = m.get("content", "")
                if content:
                    lines.append(f"ASSISTANT: {content[:500]}")
            elif role == "tool":
                raw = m.get("content", "")
                tool_name = m.get("name", "")
                try:
                    parsed = json.loads(raw)
                    status = parsed.get("status", "?")
                    output = parsed.get("output", "")[:350]
                    label = f"TOOL_RESULT({tool_name})" if tool_name else "TOOL_RESULT"
                    lines.append(f"{label}: {status} — {output}")
                except (json.JSONDecodeError, AttributeError):
                    lines.append(f"TOOL_RESULT: {raw[:400]}")
            elif role == "user":
                content = m.get("content", "")[:400]
                lines.append(f"USER: {content}")
        return "\n".join(lines)

    def set_history_budget(self, budget_tokens: int) -> None:
        """Set a dynamic token budget for conversation history.

        Called by the orchestrator before each LLM call with the remaining
        tokens after accounting for system prompt, tool definitions, and
        completion reserve.  Takes precedence over ``_max_context_tokens``
        when positive.  Triggers an immediate prune so messages are
        trimmed before the LLM call.
        """
        self._dynamic_history_budget = max(budget_tokens, 0)
        if self._dynamic_history_budget > 0:
            self._prune()

    def estimated_tokens(self) -> int:
        """Return the estimated total token count across all messages."""
        return sum(_estimate_message_tokens(m) for m in self._messages)

    def _prune(self) -> None:
        """Keep system message + last N messages, preserving tool_call/result pairs.

        Applies two passes:
        1. Message-count cap (fast, coarse).
        2. Token-budget cap (estimates tokens, drops oldest turns until under budget).
        """
        self._prune_by_count()
        budget = self._dynamic_history_budget or self._max_context_tokens
        if budget > 0:
            self._prune_by_tokens(budget)

    _CRITICAL_TOOL_ARG_KEYS: dict[str, tuple[str, ...]] = {
        "request_secret": ("name",),
        "web_search": ("query",),
        "search_docs": ("query",),
        "manage_galaxy": ("action", "collection_name"),
        "execute_playbook": ("playbook", "mode"),
        "generate_playbook": ("filename",),
    }

    def _journal_from_message(self, msg: dict[str, Any]) -> None:
        """Extract a compact progress entry from a message about to be pruned."""
        if msg.get("role") == "assistant" and "tool_calls" in msg:
            tools = []
            extras: list[str] = []
            for tc in msg["tool_calls"]:
                fn = tc.get("function", {})
                name = fn.get("name", "?")
                tools.append(name)
                arg_keys = self._CRITICAL_TOOL_ARG_KEYS.get(name)
                if arg_keys:
                    try:
                        args = fn.get("arguments", {})
                        if isinstance(args, str):
                            args = json.loads(args)
                        vals = [f"{k}={args[k]}" for k in arg_keys if k in args]
                        if vals:
                            extras.append(f"{name}({', '.join(vals)})")
                    except (json.JSONDecodeError, TypeError):
                        pass
            entry = f"called {', '.join(tools)}"
            if extras:
                entry += f" [{'; '.join(extras)}]"
            content = msg.get("content", "")
            if content and len(content) > 5:
                snippet = content[:120].replace("\n", " ").strip()
                entry += f" — {snippet}"
            self._append_journal(entry)
        elif msg.get("role") == "tool":
            try:
                parsed = json.loads(msg.get("content", "{}"))
                status = parsed.get("status", "?")
                output = parsed.get("output", "")[:150].replace("\n", " ")
                self._append_journal(f"  → {status}: {output}")
            except (json.JSONDecodeError, AttributeError):
                pass

    def _append_journal(self, entry: str) -> None:
        trimmed = entry[:self._JOURNAL_ENTRY_MAX_CHARS]
        self._progress_journal.append(trimmed)
        if len(self._progress_journal) > self._JOURNAL_MAX_ENTRIES:
            self._progress_journal = self._progress_journal[-self._JOURNAL_MAX_ENTRIES:]

    @staticmethod
    def _align_cut_to_tool_boundary(msgs: list[dict[str, Any]], cut: int) -> int:
        """Advance cut past orphaned tool messages and any assistant whose
        tool results would be split across the boundary."""
        while cut < len(msgs) and msgs[cut].get("role") == "tool":
            cut += 1
        if cut < len(msgs) and msgs[cut].get("role") == "assistant" and "tool_calls" in msgs[cut]:
            expected_ids = {tc.get("id") for tc in msgs[cut]["tool_calls"]}
            has_results_after = any(
                m.get("role") == "tool" and m.get("tool_call_id") in expected_ids
                for m in msgs[cut + 1:]
            )
            if not has_results_after:
                cut += 1
        return cut

    def _prune_by_count(self) -> None:
        if len(self._messages) <= self._max_messages:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]

        keep = self._max_messages - len(system_msgs)
        if keep >= len(other_msgs):
            return

        cut = len(other_msgs) - keep
        cut = self._align_cut_to_tool_boundary(other_msgs, cut)

        for m in other_msgs[:cut]:
            self._journal_from_message(m)
        self._messages = system_msgs + other_msgs[cut:]

    def _prune_by_tokens(self, budget_override: int = 0) -> None:
        cap = budget_override or self._max_context_tokens
        total = sum(_estimate_message_tokens(m) for m in self._messages)
        if total <= cap:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]
        if budget_override:
            budget = budget_override
        else:
            system_tokens = sum(_estimate_message_tokens(m) for m in system_msgs)
            budget = cap - system_tokens

        while other_msgs and sum(_estimate_message_tokens(m) for m in other_msgs) > budget:
            removed = other_msgs.pop(0)
            self._journal_from_message(removed)
            if removed.get("role") == "assistant" and "tool_calls" in removed:
                expected_ids = {tc.get("id") for tc in removed["tool_calls"]} - {None}
                while other_msgs and other_msgs[0].get("role") == "tool" and other_msgs[0].get("tool_call_id") in expected_ids:
                    dropped_tool = other_msgs.pop(0)
                    self._journal_from_message(dropped_tool)

        self._messages = system_msgs + other_msgs

    def ensure_integrity(self) -> int:
        """Ensure all assistant tool_calls have matching tool result messages.

        Performs three repairs:
        0. Removes orphaned tool-result messages whose assistant was pruned.
        1. Moves non-tool messages that are wedged between an assistant
           tool_calls message and its tool results to after the tool results.
           Many LLM providers (e.g. DeepSeek) require tool results to be
           contiguous immediately after the assistant message.
        2. Inserts synthetic error tool results for any orphaned tool_call_ids.

        Returns the number of repairs made.  Call before sending to the LLM.
        """
        repairs = 0

        all_tc_ids: set[str] = set()
        for m in self._messages:
            if m.get("role") == "assistant" and "tool_calls" in m:
                for tc in m["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id:
                        all_tc_ids.add(tc_id)
        before = len(self._messages)
        self._messages = [
            m for m in self._messages
            if not (m.get("role") == "tool" and m.get("tool_call_id") not in all_tc_ids)
        ]
        orphans_removed = before - len(self._messages)
        repairs += orphans_removed

        i = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if msg.get("role") != "assistant" or "tool_calls" not in msg:
                i += 1
                continue

            expected_ids = {tc.get("id") for tc in msg["tool_calls"]} - {None}

            tool_msgs: list[dict[str, Any]] = []
            displaced_msgs: list[dict[str, Any]] = []
            j = i + 1
            while j < len(self._messages):
                nxt = self._messages[j]
                if nxt.get("role") == "tool" and nxt.get("tool_call_id") in expected_ids:
                    tool_msgs.append(nxt)
                elif nxt.get("role") == "assistant":
                    break
                else:
                    displaced_msgs.append(nxt)
                j += 1

            found_ids = {m["tool_call_id"] for m in tool_msgs}
            missing = expected_ids - found_ids

            needs_reorder = bool(displaced_msgs and tool_msgs)
            needs_synthetic = bool(missing)

            if needs_reorder or needs_synthetic:
                end = j
                self._messages[i + 1:end] = []

                insert_at = i + 1
                for tm in tool_msgs:
                    self._messages.insert(insert_at, tm)
                    insert_at += 1

                for tc in msg["tool_calls"]:
                    tc_id = tc.get("id")
                    if tc_id and tc_id in missing:
                        self._messages.insert(insert_at, {
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": '{"status":"error","output":"Tool call was not executed (loop break or timeout)."}',
                        })
                        insert_at += 1
                        repairs += 1

                for dm in displaced_msgs:
                    self._messages.insert(insert_at, dm)
                    insert_at += 1

                if needs_reorder:
                    repairs += 1

            i += 1
        return repairs

    def clear(self) -> None:
        system_msgs = [m for m in self._messages if m["role"] == "system"]
        self._messages = system_msgs
        self._metadata.clear()
        self._progress_journal.clear()
