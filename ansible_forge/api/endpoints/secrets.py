"""Secure secret submission endpoints — values never reach the LLM."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ansible_forge.api.endpoints.chat import get_orchestrator
from ansible_forge.api.middleware.auth import verify_api_key

router = APIRouter()


class SecretSubmitRequest(BaseModel):
    name: str = Field(..., min_length=1, description="Secret variable name")
    value: str = Field(..., min_length=1, description="Secret value")
    description: str = Field(default="", description="Optional description")


class SecretInfo(BaseModel):
    name: str
    description: str


class SecretsListResponse(BaseModel):
    session_id: str
    secrets: list[SecretInfo]


class SecretResponse(BaseModel):
    session_id: str
    name: str
    status: str
    message: str


@router.post(
    "/chat/{session_id}/secrets",
    response_model=SecretResponse,
)
async def submit_secret(
    session_id: str,
    body: SecretSubmitRequest,
    _: Any = Depends(verify_api_key),
) -> SecretResponse:
    """Submit a secret value securely. The value is stored in the session vault
    and injected into ansible-runner at execution time. It is never sent to
    the LLM or included in conversation history."""
    orch = get_orchestrator()
    if orch.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    orch.store_secret(session_id, body.name, body.value, body.description)
    return SecretResponse(
        session_id=session_id,
        name=body.name,
        status="stored",
        message=f"Secret '{body.name}' securely stored.",
    )


@router.get(
    "/chat/{session_id}/secrets",
    response_model=SecretsListResponse,
)
async def list_secrets(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> SecretsListResponse:
    """List secret names for a session (never returns values)."""
    orch = get_orchestrator()
    if orch.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    items = orch.list_secrets(session_id)
    return SecretsListResponse(
        session_id=session_id,
        secrets=[SecretInfo(**s) for s in items],
    )


@router.post(
    "/chat/{session_id}/secrets/cancel",
    response_model=SecretResponse,
)
async def cancel_secret(
    session_id: str,
    _: Any = Depends(verify_api_key),
) -> SecretResponse:
    """Cancel all pending secret requests for a session, unblocking the agent."""
    orch = get_orchestrator()
    session_vault = orch._secret_vault.for_session(session_id)
    session_vault.cancel_all_pending()

    state = orch.get_session(session_id)
    if state and state.status == "awaiting_secret":
        state.status = "active"

    return SecretResponse(
        session_id=session_id,
        name="*",
        status="cancelled",
        message="Pending secret requests cancelled.",
    )


@router.delete(
    "/chat/{session_id}/secrets/{secret_name}",
    response_model=SecretResponse,
)
async def delete_secret(
    session_id: str,
    secret_name: str,
    _: Any = Depends(verify_api_key),
) -> SecretResponse:
    """Delete a specific secret from the session vault."""
    orch = get_orchestrator()
    if orch.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")

    deleted = orch.delete_secret(session_id, secret_name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Secret '{secret_name}' not found")
    return SecretResponse(
        session_id=session_id,
        name=secret_name,
        status="deleted",
        message=f"Secret '{secret_name}' removed.",
    )
