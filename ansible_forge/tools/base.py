"""Base tool interface and result model for all Ansible tools."""

from __future__ import annotations

import abc
import json as _json
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

_MAX_LLM_CONTEXT_CHARS = 6000


class ToolStatus(StrEnum):
    SUCCESS = "success"
    ERROR = "error"
    NEEDS_APPROVAL = "needs_approval"


class ToolResult(BaseModel):
    """Standard result returned by every tool execution."""

    status: ToolStatus = ToolStatus.SUCCESS
    output: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    error: str | None = None

    @classmethod
    def ok(cls, output: str = "", **data: Any) -> ToolResult:
        return cls(status=ToolStatus.SUCCESS, output=output, data=data)

    @classmethod
    def fail(cls, error: str, **data: Any) -> ToolResult:
        return cls(status=ToolStatus.ERROR, output="", error=error, data=data)

    @classmethod
    def approval_required(cls, output: str = "", **data: Any) -> ToolResult:
        return cls(status=ToolStatus.NEEDS_APPROVAL, output=output, data=data)

    def to_llm_context(self) -> str:
        d: dict[str, Any] = {"status": self.status.value}
        if self.output:
            out = self.output[:_MAX_LLM_CONTEXT_CHARS]
            if len(self.output) > _MAX_LLM_CONTEXT_CHARS:
                out += "...[truncated]"
            d["output"] = out
        if self.error:
            d["error"] = self.error[:1000]
        if self.status == ToolStatus.ERROR and self.data:
            for key in ("raw_stdout", "stderr", "summary"):
                value = self.data.get(key)
                if not value:
                    continue
                if isinstance(value, dict):
                    text = _json.dumps(value)
                else:
                    text = str(value)
                if len(text) > 1500:
                    text = text[:1500] + "...[truncated]"
                d[key] = text
        return _json.dumps(d)


class BaseTool(abc.ABC):
    """Abstract base class for every AnsibleForge tool.

    Subclasses must define ``name``, ``description``, ``parameters`` (JSON Schema),
    and implement ``execute``.
    """

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique tool name used in function-calling."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human-readable description shown to the LLM."""

    @property
    @abc.abstractmethod
    def parameters(self) -> dict[str, Any]:
        """JSON Schema object describing the tool's parameters."""

    @abc.abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        """Run the tool with the given arguments and return a result."""

    def to_openai_tool(self) -> dict[str, Any]:
        """Serialize to the OpenAI-compatible tool definition used by LiteLLM."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
