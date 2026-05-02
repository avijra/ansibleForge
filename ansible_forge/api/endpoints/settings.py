"""Runtime LLM settings endpoint — configure model, provider, and API keys from the UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.api.endpoints.health import reset_llm_status_cache
from ansible_forge.config import (
    clear_runtime_llm,
    effective_llm_model,
    effective_llm_provider,
    get_runtime_llm,
    get_settings,
    update_runtime_llm,
)

router = APIRouter()


class LLMSettingsResponse(BaseModel):
    provider: str = Field(description="Active LLM provider")
    model: str = Field(description="Active LLM model")
    api_key_set: bool = Field(description="Whether a runtime API key is configured")
    api_base: str | None = Field(default=None, description="Custom API base URL")
    temperature: float = Field(description="Sampling temperature")
    max_tokens: int = Field(description="Max output tokens")
    source: str = Field(description="'runtime' if overridden, 'env' if using .env defaults")


class LLMSettingsUpdate(BaseModel):
    provider: str | None = Field(default=None, description="LLM provider (e.g. openai, anthropic, ollama)")
    model: str | None = Field(default=None, description="Full model identifier (e.g. openai/gpt-4o)")
    api_key: str | None = Field(default=None, description="Provider API key")
    api_base: str | None = Field(default=None, description="Custom API base URL (for Ollama, vLLM, etc.)")
    temperature: float | None = Field(default=None, ge=0, le=2, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, ge=1, le=128_000, description="Max output tokens")


@router.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    _: Any = Depends(verify_api_key),
) -> LLMSettingsResponse:
    settings = get_settings()
    rt = get_runtime_llm()
    is_overridden = bool(rt.model or rt.provider)

    has_runtime_key = rt.api_key is not None
    has_env_key = bool(settings.openai_api_key or settings.anthropic_api_key)

    return LLMSettingsResponse(
        provider=effective_llm_provider(),
        model=effective_llm_model(),
        api_key_set=has_runtime_key or has_env_key,
        api_base=rt.api_base,
        temperature=rt.temperature if rt.temperature is not None else settings.llm_temperature,
        max_tokens=rt.max_tokens if rt.max_tokens is not None else settings.llm_max_tokens,
        source="runtime" if is_overridden else "env",
    )


@router.put("/settings/llm", response_model=LLMSettingsResponse)
async def update_llm_settings(
    body: LLMSettingsUpdate,
    _: Any = Depends(verify_api_key),
) -> LLMSettingsResponse:
    patch = body.model_dump(exclude_none=True)
    update_runtime_llm(patch)
    reset_llm_status_cache()
    return await get_llm_settings()


@router.delete("/settings/llm", response_model=LLMSettingsResponse)
async def reset_llm_settings(
    _: Any = Depends(verify_api_key),
) -> LLMSettingsResponse:
    clear_runtime_llm()
    reset_llm_status_cache()
    return await get_llm_settings()
