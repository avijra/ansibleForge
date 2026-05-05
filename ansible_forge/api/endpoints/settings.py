"""Runtime LLM settings endpoint — configure model, provider, and API keys from the UI."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ansible_forge.api.endpoints.health import reset_llm_status_cache
from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.config import (
    APPROVED_MODEL_IDS,
    APPROVED_MODELS,
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
    warning: str | None = Field(default=None, description="Warning if using an untested model")


class LLMSettingsUpdate(BaseModel):
    provider: str | None = Field(default=None, description="LLM provider (e.g. openai, anthropic, ollama)")
    model: str | None = Field(default=None, description="Full model identifier (e.g. openai/gpt-4o)")
    api_key: str | None = Field(default=None, description="Provider API key")
    api_base: str | None = Field(default=None, description="Custom API base URL (for Ollama, vLLM, etc.)")
    temperature: float | None = Field(default=None, ge=0, le=2, description="Sampling temperature")
    max_tokens: int | None = Field(default=None, ge=1, le=128_000, description="Max output tokens")


def _model_warning(model: str) -> str | None:
    if not model or model in APPROVED_MODEL_IDS:
        return None
    return (
        "This model has not been tested with Tuyere. "
        "Tool calling, safety rules, and multi-step reliability may be degraded."
    )


@router.get("/settings/llm/models")
async def get_approved_models(
    _: Any = Depends(verify_api_key),
) -> list[dict[str, str]]:
    return APPROVED_MODELS


@router.get("/settings/llm", response_model=LLMSettingsResponse)
async def get_llm_settings(
    _: Any = Depends(verify_api_key),
) -> LLMSettingsResponse:
    settings = get_settings()
    rt = get_runtime_llm()
    is_overridden = bool(rt.model or rt.provider)

    has_runtime_key = rt.api_key is not None
    has_env_key = bool(settings.openai_api_key or settings.anthropic_api_key)
    active_model = effective_llm_model()

    return LLMSettingsResponse(
        provider=effective_llm_provider(),
        model=active_model,
        api_key_set=has_runtime_key or has_env_key,
        api_base=rt.api_base,
        temperature=rt.temperature if rt.temperature is not None else settings.llm_temperature,
        max_tokens=rt.max_tokens if rt.max_tokens is not None else settings.llm_max_tokens,
        source="runtime" if is_overridden else "env",
        warning=_model_warning(active_model),
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


@router.post("/settings/llm/test")
async def test_llm_connection(
    body: LLMSettingsUpdate,
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    test_model = body.model or effective_llm_model()
    test_key = body.api_key
    test_base = body.api_base

    if not test_model:
        return {"ok": False, "error": "No model configured."}

    try:
        from litellm import acompletion

        kwargs: dict[str, Any] = {
            "model": test_model,
            "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
            "max_tokens": 5,
            "temperature": 0,
        }
        if test_key:
            kwargs["api_key"] = test_key
        if test_base:
            kwargs["api_base"] = test_base
        resp = await acompletion(**kwargs)
        reply = resp.choices[0].message.content or ""
        return {"ok": True, "reply": reply.strip()[:50], "model": test_model}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300], "model": test_model}


@router.delete("/settings/llm", response_model=LLMSettingsResponse)
async def reset_llm_settings(
    _: Any = Depends(verify_api_key),
) -> LLMSettingsResponse:
    clear_runtime_llm()
    reset_llm_status_cache()
    return await get_llm_settings()
