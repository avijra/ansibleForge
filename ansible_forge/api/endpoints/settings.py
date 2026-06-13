"""Runtime settings endpoints — configure LLM and Execution Environment from the UI."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ansible_forge.api.endpoints.health import reset_llm_status_cache
from ansible_forge.api.middleware.auth import verify_api_key
from ansible_forge.config import (
    APPROVED_MODEL_IDS,
    APPROVED_MODELS,
    clear_runtime_ee,
    clear_runtime_llm,
    effective_ee_container_runtime,
    effective_ee_enabled,
    effective_ee_host_mode,
    effective_ee_image,
    effective_ee_remote_host,
    effective_ee_remote_workspace_root,
    effective_llm_model,
    effective_llm_provider,
    get_runtime_ee,
    get_runtime_llm,
    get_settings,
    update_runtime_ee,
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


class ExecutionSettingsResponse(BaseModel):
    enabled: bool = Field(description="Whether EE container mode is active")
    image: str = Field(description="Container image name")
    container_runtime: str = Field(description="Container runtime (docker or podman)")
    runtime_available: bool = Field(description="Whether the container runtime binary is found")
    host_mode: str = Field(description="Execution host mode: local or remote")
    remote_host: str | None = Field(default=None, description="Remote SSH host (user@hostname)")
    remote_workspace_root: str = Field(description="Remote workspace sync root directory")
    image_ready: bool = Field(description="Whether the EE image is available on the target host")
    image_pull_status: Literal["idle", "pulling", "ready", "failed"] = Field(
        description="Current EE image pull status"
    )
    image_pull_message: str = Field(description="Human-readable pull status message")
    source: str = Field(description="'runtime' if overridden, 'env' if using .env defaults")


class ExecutionSettingsUpdate(BaseModel):
    enabled: bool | None = Field(default=None, description="Enable/disable EE container mode")
    image: str | None = Field(default=None, description="Container image name")
    container_runtime: Literal["docker", "podman"] | None = Field(
        default=None,
        description="Container runtime (docker or podman)",
    )
    host_mode: Literal["local", "remote"] | None = Field(
        default=None,
        description="Execution host mode: local or remote",
    )
    remote_host: str | None = Field(default=None, description="Remote SSH host (user@hostname)")
    remote_workspace_root: str | None = Field(
        default=None, description="Remote workspace sync root directory"
    )


async def _build_execution_settings_response() -> ExecutionSettingsResponse:
    from ansible_forge.tools.ee_runtime import (
        container_runtime_available,
        ee_image_available,
        get_pull_state,
    )

    rt = get_runtime_ee()
    is_overridden = any(
        value is not None
        for value in (
            rt.enabled,
            rt.image,
            rt.container_runtime,
            rt.host_mode,
            rt.remote_host,
            rt.remote_workspace_root,
        )
    )
    available, _ = container_runtime_available()
    image_available, _ = await ee_image_available()
    pull_state = get_pull_state()

    image_ready = image_available or pull_state["status"] == "ready"
    raw_status = str(pull_state["status"])
    if image_available and raw_status != "pulling":
        pull_status: Literal["idle", "pulling", "ready", "failed"] = "ready"
    elif raw_status == "pulling":
        pull_status = "pulling"
    elif raw_status == "failed":
        pull_status = "failed"
    elif raw_status == "ready":
        pull_status = "ready"
    else:
        pull_status = "idle"

    return ExecutionSettingsResponse(
        enabled=effective_ee_enabled(),
        image=effective_ee_image(),
        container_runtime=effective_ee_container_runtime(),
        runtime_available=available,
        host_mode=effective_ee_host_mode(),
        remote_host=effective_ee_remote_host(),
        remote_workspace_root=effective_ee_remote_workspace_root(),
        image_ready=image_ready,
        image_pull_status=pull_status,
        image_pull_message=str(pull_state["message"]),
        source="runtime" if is_overridden else "env",
    )


async def _maybe_schedule_image_pull(was_enabled: bool, patch: dict[str, Any]) -> None:
    from ansible_forge.tools.ee_runtime import schedule_ee_image_pull

    if effective_ee_enabled():
        schedule_ee_image_pull()


@router.get("/settings/execution", response_model=ExecutionSettingsResponse)
async def get_execution_settings(
    _: Any = Depends(verify_api_key),
) -> ExecutionSettingsResponse:
    return await _build_execution_settings_response()


@router.put("/settings/execution", response_model=ExecutionSettingsResponse)
async def update_execution_settings(
    body: ExecutionSettingsUpdate,
    _: Any = Depends(verify_api_key),
) -> ExecutionSettingsResponse:
    was_enabled = effective_ee_enabled()
    patch = body.model_dump(exclude_none=True)
    update_runtime_ee(patch)
    from ansible_forge.tools.workspace_sync import clear_sync_cache

    clear_sync_cache()
    await _maybe_schedule_image_pull(was_enabled, patch)
    return await _build_execution_settings_response()


@router.post("/settings/execution/pull", response_model=ExecutionSettingsResponse)
async def pull_execution_image(
    _: Any = Depends(verify_api_key),
) -> ExecutionSettingsResponse:
    from ansible_forge.tools.ee_runtime import schedule_ee_image_pull

    if not effective_ee_enabled():
        return await _build_execution_settings_response()
    schedule_ee_image_pull()
    return await _build_execution_settings_response()


@router.post("/settings/execution/test-remote")
async def test_execution_remote(
    _: Any = Depends(verify_api_key),
) -> dict[str, Any]:
    from ansible_forge.tools.ee_runtime import test_remote_connection

    if effective_ee_host_mode() != "remote":
        return {"ok": False, "error": "Execution host mode is not set to remote"}
    ok, message = await test_remote_connection()
    return {"ok": ok, "message": message}


@router.delete("/settings/execution", response_model=ExecutionSettingsResponse)
async def reset_execution_settings(
    _: Any = Depends(verify_api_key),
) -> ExecutionSettingsResponse:
    clear_runtime_ee()
    from ansible_forge.tools.workspace_sync import clear_sync_cache

    clear_sync_cache()
    return await _build_execution_settings_response()
