"""Health and readiness check endpoints."""

from __future__ import annotations

import functools

from fastapi import APIRouter
from pydantic import BaseModel

from ansible_forge import __version__
from ansible_forge.api.schemas.responses import HealthResponse
from ansible_forge.config import effective_llm_model, effective_llm_provider
from ansible_forge.tools.registry import create_default_registry

router = APIRouter()


@functools.lru_cache(maxsize=1)
def _cached_tool_names() -> list[str]:
    return create_default_registry().tool_names


class ReadinessResponse(BaseModel):
    ready: bool
    version: str
    checks: dict[str, bool]


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        version=__version__,
        llm_provider=effective_llm_provider(),
        llm_model=effective_llm_model(),
        tools_available=_cached_tool_names(),
    )


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    checks = {
        "tools_loaded": len(_cached_tool_names()) > 0,
        "llm_configured": bool(effective_llm_model()),
    }
    return ReadinessResponse(
        ready=all(checks.values()),
        version=__version__,
        checks=checks,
    )
