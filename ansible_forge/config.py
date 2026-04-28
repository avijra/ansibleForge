"""Centralised configuration loaded from environment / .env file."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANSIBLEFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────────────
    llm_provider: str = "anthropic"
    llm_model: str = "anthropic/claude-sonnet-4-20250514"
    llm_fallback_models: list[str] = Field(default_factory=list)
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16384
    ollama_base_url: str = "http://localhost:11434"

    # Provider keys read without prefix so LiteLLM picks them up too
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # ── Agent ──────────────────────────────────────────────────────
    max_agent_steps: int = 100
    workspace_dir: Path = Path("/tmp/ansibleforge")
    workspace_ttl_seconds: int = 3600

    # ── Knowledge Graph ───────────────────────────────────────────
    knowledge_enabled: bool = True
    knowledge_dir: Path = Path.home() / ".ansibleforge" / "knowledge"

    # ── API ────────────────────────────────────────────────────────
    api_key: str | None = None
    host: str = "0.0.0.0"
    port: int = 8420
    log_level: str = "info"


class RuntimeLLMConfig(BaseModel):
    """Mutable LLM configuration that can be changed at runtime via the API."""

    provider: str = ""
    model: str = ""
    api_key: str | None = None
    api_base: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None


_settings: Settings | None = None
_runtime_llm = RuntimeLLMConfig()
_lock = threading.Lock()


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def get_runtime_llm() -> RuntimeLLMConfig:
    return _runtime_llm


def update_runtime_llm(patch: dict[str, Any]) -> RuntimeLLMConfig:
    global _runtime_llm
    with _lock:
        current = _runtime_llm.model_dump()
        current.update({k: v for k, v in patch.items() if v is not None})
        _runtime_llm = RuntimeLLMConfig(**current)
    return _runtime_llm


def clear_runtime_llm() -> None:
    global _runtime_llm
    with _lock:
        _runtime_llm = RuntimeLLMConfig()


def effective_llm_provider() -> str:
    rt = get_runtime_llm()
    if rt.provider:
        return rt.provider
    return get_settings().llm_provider


def effective_llm_model() -> str:
    rt = get_runtime_llm()
    if rt.model:
        return rt.model
    return get_settings().llm_model
