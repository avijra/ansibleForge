"""Request schemas for the AnsibleForge API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, description="Natural language request")
    session_id: str | None = Field(
        default=None, description="Existing session ID to continue a conversation"
    )
    model: str | None = Field(
        default=None, description="Override the default LLM model for this request"
    )


class ApprovalRequest(BaseModel):
    approved: bool = Field(..., description="Whether to approve the pending execution")
    feedback: str = Field(default="", description="Feedback when rejecting")


class ExecuteRequest(BaseModel):
    playbook_content: str = Field(..., description="Full playbook YAML content")
    inventory_content: str = Field(default="", description="Inventory content (YAML or INI)")
    mode: str = Field(default="check", description="Execution mode: 'check' or 'apply'")
    extra_vars: dict[str, Any] = Field(default_factory=dict)


class LintRequest(BaseModel):
    content: str = Field(..., description="Playbook or role YAML to lint")
    profile: str = Field(default="moderate", description="Lint profile")


class CollectionInstallRequest(BaseModel):
    name: str = Field(..., description="Collection FQCN (e.g. community.general)")
    version: str | None = Field(default=None, description="Version constraint")
