"""Tests for conversation Memory."""

from __future__ import annotations

from ansible_forge.agent.memory import Memory


class TestMemory:
    def test_add_system_sets_first_message(self) -> None:
        mem = Memory()
        mem.add_system("You are AnsibleForge")
        assert mem.messages[0]["role"] == "system"
        assert mem.message_count == 1

    def test_system_message_replaced_not_duplicated(self) -> None:
        mem = Memory()
        mem.add_system("v1")
        mem.add_system("v2")
        assert mem.message_count == 1
        assert mem.messages[0]["content"] == "v2"

    def test_conversation_flow(self) -> None:
        mem = Memory()
        mem.add_system("system")
        mem.add_user("hello")
        mem.add_assistant(content="hi there")
        assert mem.message_count == 3
        assert mem.messages[1]["role"] == "user"
        assert mem.messages[2]["role"] == "assistant"

    def test_tool_result_added(self) -> None:
        mem = Memory()
        mem.add_tool_result("call_123", '{"output": "done"}')
        assert mem.messages[-1]["role"] == "tool"
        assert mem.messages[-1]["tool_call_id"] == "call_123"

    def test_pruning_keeps_system(self) -> None:
        mem = Memory(max_messages=5)
        mem.add_system("system prompt")
        for i in range(10):
            mem.add_user(f"msg {i}")
        assert mem.message_count <= 5
        assert mem.messages[0]["role"] == "system"

    def test_clear_keeps_system(self) -> None:
        mem = Memory()
        mem.add_system("system")
        mem.add_user("hello")
        mem.clear()
        assert mem.message_count == 1
        assert mem.messages[0]["role"] == "system"

    def test_metadata(self) -> None:
        mem = Memory()
        mem.set_metadata("workspace", "/tmp/test")
        assert mem.get_metadata("workspace") == "/tmp/test"
        assert mem.get_metadata("missing", "default") == "default"
