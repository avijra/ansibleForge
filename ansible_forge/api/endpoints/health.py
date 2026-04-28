"""Health check endpoint."""

from __future__ import annotations

from fastapi import APIRouter

from ansible_forge import __version__
from ansible_forge.api.schemas.responses import HealthResponse
from ansible_forge.config import effective_llm_model, effective_llm_provider
from ansible_forge.tools.registry import create_default_registry

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    registry = create_default_registry()
    return HealthResponse(
        status="healthy",
        version=__version__,
        llm_provider=effective_llm_provider(),
        llm_model=effective_llm_model(),
        tools_available=registry.tool_names,
    )
