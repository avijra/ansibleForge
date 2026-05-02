"""Conversation and context memory for agent sessions."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ansible_forge.safety.secret_vault import SessionVault


class Memory:
    """Stores conversation history and tool results for a single session.

    Keeps messages in OpenAI chat format and prunes to stay within token budgets.
    Uses paired pruning to ensure tool_call messages always have their
    corresponding tool result messages (orphaned references break the LLM).

    When a ``SessionVault`` is attached, all incoming text is scrubbed so that
    raw secret values are replaced with ``<<SECRET:name>>`` placeholders before
    they ever enter the message list (and are therefore never sent to the LLM).
    """

    def __init__(self, max_messages: int = 500) -> None:
        self._messages: list[dict[str, Any]] = []
        self._max_messages = max_messages
        self._metadata: dict[str, Any] = {}
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
        """
        result: list[Any] = []
        for m in self._messages:
            result.append({k: v for k, v in m.items() if not k.startswith("_")})
        return result

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def add_system(self, content: str) -> None:
        if self._messages and self._messages[0]["role"] == "system":
            self._messages[0]["content"] = content
        else:
            self._messages.insert(0, {"role": "system", "content": content})

    def add_user(self, content: str) -> None:
        self._messages.append({"role": "user", "content": self._redact(content)})
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

        When pruning, we find a safe cut point that doesn't split an assistant
        message with tool_calls from its subsequent tool result messages.
        """
        if len(self._messages) <= self._max_messages:
            return

        system_msgs = [m for m in self._messages if m["role"] == "system"]
        other_msgs = [m for m in self._messages if m["role"] != "system"]

        keep = self._max_messages - len(system_msgs)
        if keep >= len(other_msgs):
            return

        cut = len(other_msgs) - keep
        # Walk forward from the cut point to avoid splitting a tool_call/result pair
        while cut < len(other_msgs):
            msg = other_msgs[cut]
            if msg.get("role") == "tool":
                cut += 1
            else:
                break

        self._messages = system_msgs + other_msgs[cut:]

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
