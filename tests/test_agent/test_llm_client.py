"""Tests for LLM client utilities."""

from __future__ import annotations

from ansible_forge.agent.llm_client import _patch_deepseek_reasoning


class TestPatchDeepseekReasoning:
    def test_noop_for_non_deepseek(self) -> None:
        messages = [
            {"role": "system", "content": "you are helpful"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi", "tool_calls": []},
        ]
        result = _patch_deepseek_reasoning("openai/gpt-4o", messages)
        assert result is messages

    def test_injects_reasoning_content_on_assistant(self) -> None:
        messages = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "thinking", "tool_calls": [{"id": "1", "function": {"name": "foo", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "1", "content": "result"},
        ]
        result = _patch_deepseek_reasoning("deepseek/deepseek-v4-pro", messages)
        assert result[1]["reasoning_content"] == ""
        assert result[0].get("reasoning_content") is None
        assert result[2].get("reasoning_content") is None

    def test_preserves_existing_reasoning_content(self) -> None:
        messages = [
            {"role": "assistant", "content": "hi", "reasoning_content": "I thought about it"},
        ]
        result = _patch_deepseek_reasoning("deepseek/deepseek-v4-flash", messages)
        assert result[0]["reasoning_content"] == "I thought about it"

    def test_handles_empty_messages(self) -> None:
        assert _patch_deepseek_reasoning("deepseek/deepseek-v4-pro", []) == []

    def test_case_insensitive_model_match(self) -> None:
        messages = [{"role": "assistant", "content": "hi"}]
        result = _patch_deepseek_reasoning("DeepSeek/DeepSeek-V4-Pro", messages)
        assert result[0]["reasoning_content"] == ""
