"""Response schemas for the AnsibleForge API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatResponse(BaseModel):
    session_id: str
    status: str
    message: str = ""
    events: list[dict[str, Any]] = Field(default_factory=list)


class SessionStatusResponse(BaseModel):
    session_id: str
    status: str
    step_count: int
    workspace_path: str


class ApprovalResponse(BaseModel):
    session_id: str
    status: str
    message: str


class ExecuteResponse(BaseModel):
    status: str
    output: str
    data: dict[str, Any] = Field(default_factory=dict)


class LintResponse(BaseModel):
    passed: bool
    violation_count: int
    violations: list[dict[str, Any]] = Field(default_factory=list)
    profile: str


class CollectionResponse(BaseModel):
    status: str
    message: str
    collections: list[dict[str, str]] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    version: str
    llm_provider: str
    llm_model: str
    tools_available: list[str] = Field(default_factory=list)
