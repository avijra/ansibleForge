"""Health and readiness check endpoints."""

from __future__ import annotations

import functools
import os
import shutil
import time

from fastapi import APIRouter
from pydantic import BaseModel

from ansible_forge import __version__
from ansible_forge.api.schemas.responses import HealthResponse
from ansible_forge.config import (
    effective_llm_model,
    effective_llm_provider,
    get_runtime_llm,
    get_settings,
)
from ansible_forge.logging import get_logger
from ansible_forge.tools.binary_resolver import resolve_terraform
from ansible_forge.tools.ee_runtime import (
    container_runtime_available,
    get_ee_image,
    is_ee_enabled,
)
from ansible_forge.tools.python_resolver import resolve_standalone_python
from ansible_forge.tools.registry import create_default_registry

logger = get_logger(__name__)

router = APIRouter()

_llm_status_cache: dict[str, object] = {"status": "unknown", "detail": "", "checked_at": 0.0}
_LLM_CHECK_INTERVAL = 60.0


@functools.lru_cache(maxsize=1)
def _cached_registry():
    return create_default_registry()


def _cached_tool_names() -> list[str]:
    return _cached_registry().tool_names


def _check_llm_key_configured() -> tuple[str, str]:
    provider = effective_llm_provider()
    rt = get_runtime_llm()
    settings = get_settings()

    if not provider:
        return "degraded", "No LLM provider configured — open Settings to set one up"

    if rt.api_key:
        return "healthy", ""

    key_checks: dict[str, str | None] = {
        "openai": os.environ.get("OPENAI_API_KEY") or settings.openai_api_key,
        "anthropic": os.environ.get("ANTHROPIC_API_KEY") or settings.anthropic_api_key,
        "deepseek": os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("OPENAI_API_KEY") or settings.openai_api_key,
        "ollama": "local",
    }

    key = key_checks.get(provider)
    _placeholder_patterns = ("sk-...", "sk-ant-...", "your-", "YOUR_", "xxx", "placeholder", "CHANGE_ME")
    if key and not any(key.strip().lower().startswith(p.lower()) for p in _placeholder_patterns):
        return "healthy", ""

    return "degraded", f"No API key configured for {provider}"


def _get_llm_status() -> tuple[str, str]:
    now = time.time()
    if now - float(str(_llm_status_cache.get("checked_at", 0))) < _LLM_CHECK_INTERVAL:
        return str(_llm_status_cache["status"]), str(_llm_status_cache["detail"])

    status, detail = _check_llm_key_configured()
    _llm_status_cache["status"] = status
    _llm_status_cache["detail"] = detail
    _llm_status_cache["checked_at"] = now
    return status, detail


def reset_llm_status_cache() -> None:
    _llm_status_cache["checked_at"] = 0.0


class ReadinessResponse(BaseModel):
    ready: bool
    version: str
    checks: dict[str, bool]


def _check_external_tools() -> dict[str, str]:
    tools: dict[str, str] = {}

    if is_ee_enabled():
        available, detail = container_runtime_available()
        tools["container_runtime"] = detail if available else f"NOT FOUND: {detail}"
        tools["ee_image"] = get_ee_image()
    else:
        standalone_py = resolve_standalone_python()
        tools["ansible_python"] = standalone_py if standalone_py else "not installed (required for module execution)"

        for name in ("ansible-playbook", "ansible-galaxy", "ansible-inventory"):
            path = shutil.which(name)
            tools[name] = path if path else "not found"

    tf = resolve_terraform()
    tools["terraform"] = tf if tf else "not installed (auto-downloads on first use)"

    git = shutil.which("git")
    tools["git"] = git if git else "not installed"

    return tools


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    llm_status, llm_detail = _get_llm_status()
    status = "degraded" if llm_status == "degraded" else "healthy"

    return HealthResponse(
        status=status,
        version=__version__,
        llm_provider=effective_llm_provider(),
        llm_model=effective_llm_model(),
        tools_available=_cached_tool_names(),
        llm_status=llm_status,
        llm_status_detail=llm_detail,
        external_tools=_check_external_tools(),
        execution_mode="container" if is_ee_enabled() else "host",
    )


@router.get("/tools")
async def list_tools() -> list[dict[str, str]]:
    return _cached_registry().tool_summaries


@router.get("/ready", response_model=ReadinessResponse)
async def readiness_check() -> ReadinessResponse:
    llm_status, _ = _get_llm_status()
    checks = {
        "tools_loaded": len(_cached_tool_names()) > 0,
        "llm_configured": bool(effective_llm_model()),
        "llm_reachable": llm_status == "healthy",
    }
    return ReadinessResponse(
        ready=all(checks.values()),
        version=__version__,
        checks=checks,
    )
