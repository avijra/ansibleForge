"""Conversation and context memory for agent sessions."""

from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ansible_forge.safety.secret_vault import SessionVault

_CHARS_PER_TOKEN = 4


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

    def __init__(self, max_messages: int = 500, max_context_tokens: int = 0) -> None:
        self._messages: list[dict[str, Any]] = []
        self._max_messages = max_messages
        self._max_context_tokens = max_context_tokens
        self._metadata: dict[str, Any] = {}
        self._pinned_goal: str | None = None
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
        stripped.  ``reasoning_content`` is preserved because thinking-mode
        models (e.g. DeepSeek) require it passed back on every subsequent
        call.

        If older user messages have been pruned, a compact goal-reminder
        message is injected right after the system prompt so the LLM
        never loses track of the user's original request.
        """
        result: list[Any] = []
        goal_injected = False
        for m in self._messages:
            result.append({k: v for k, v in m.items() if not k.startswith("_")})
            if (
                not goal_injected
                and self._pinned_goal
                and m.get("role") == "system"
                and self._goal_pruned()
            ):
                result.append({
                    "role": "user",
                    "content": (
                        f"[CONTEXT REMINDER — original user goal, do NOT lose "
                        f"track of this]\n{self._pinned_goal}"
                    ),
                })
                result.append({
                    "role": "assistant",
                    "content": "Understood — I have the original goal in context.",
                })
                goal_injected = True
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

    def _prune(self) -> None:
        """Keep system message + last N messages, preserving tool_call/result pairs.

        Applies two passes:
        1. Message-count cap (fast, coarse).
        2. Token-budget cap (estimates tokens, drops oldest turns until under budget).
        """
        self._prune_by_count()
        if self._max_context_tokens > 0:
            self._prune_by_tokens()

    def _prune_by_count(self) -> None:
        if len(self._messages) <= self._max_messages:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]

        keep = self._max_messages - len(system_msgs)
        if keep >= len(other_msgs):
            return

        cut = len(other_msgs) - keep
        while cut < len(other_msgs):
            msg = other_msgs[cut]
            if msg.get("role") == "tool":
                cut += 1
            else:
                break

        self._messages = system_msgs + other_msgs[cut:]

    def _prune_by_tokens(self) -> None:
        total = sum(_estimate_message_tokens(m) for m in self._messages)
        if total <= self._max_context_tokens:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]
        system_tokens = sum(_estimate_message_tokens(m) for m in system_msgs)
        budget = self._max_context_tokens - system_tokens

        while other_msgs and sum(_estimate_message_tokens(m) for m in other_msgs) > budget:
            removed = other_msgs.pop(0)
            if removed.get("role") == "assistant" and "tool_calls" in removed:
                expected_ids = {tc["id"] for tc in removed["tool_calls"]}
                while other_msgs and other_msgs[0].get("role") == "tool" and other_msgs[0].get("tool_call_id") in expected_ids:
                    other_msgs.pop(0)

        self._messages = system_msgs + other_msgs

    def ensure_integrity(self) -> int:
        """Ensure all assistant tool_calls have matching tool result messages.

        Performs two repairs:
        1. Moves non-tool messages that are wedged between an assistant
           tool_calls message and its tool results to after the tool results.
           Many LLM providers (e.g. DeepSeek) require tool results to be
           contiguous immediately after the assistant message.
        2. Inserts synthetic error tool results for any orphaned tool_call_ids.

        Returns the number of repairs made.  Call before sending to the LLM.
        """
        repairs = 0
        i = 0
        while i < len(self._messages):
            msg = self._messages[i]
            if msg.get("role") != "assistant" or "tool_calls" not in msg:
                i += 1
                continue

            expected_ids = {tc["id"] for tc in msg["tool_calls"]}

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
                    if tc["id"] in missing:
                        self._messages.insert(insert_at, {
                            "role": "tool",
                            "tool_call_id": tc["id"],
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
