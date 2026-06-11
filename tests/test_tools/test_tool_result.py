"""Tests for ToolResult LLM context serialization."""

from __future__ import annotations

import json

from ansible_forge.tools.base import ToolResult, ToolStatus


class TestToolResultLLMContext:
    def test_error_includes_raw_stdout(self) -> None:
        result = ToolResult.fail(
            "Deployment failed",
            raw_stdout="ERROR: unsupported locale setting",
        )
        payload = json.loads(result.to_llm_context())
        assert payload["status"] == "error"
        assert "unsupported locale setting" in payload["raw_stdout"]
