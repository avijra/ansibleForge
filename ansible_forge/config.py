"""Centralised configuration loaded from environment / .env file."""

from __future__ import annotations

import json as _json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APPROVED_MODELS: list[dict[str, str]] = [
    {
        "provider": "anthropic",
        "model": "anthropic/claude-sonnet-4-20250514",
        "label": "Claude Sonnet 4",
        "tier": "$$$",
        "description": "Best overall — reliable tool calling, strong YAML/HCL generation",
    },
    {
        "provider": "deepseek",
        "model": "deepseek/deepseek-v4-pro",
        "label": "DeepSeek V4-Pro",
        "tier": "$$",
        "description": "Best value — frontier agentic quality, open source (MIT)",
    },
    {
        "provider": "deepseek",
        "model": "deepseek/deepseek-v4-flash",
        "label": "DeepSeek V4-Flash",
        "tier": "$",
        "description": "Cheapest — fast, good for simpler tasks, self-hostable",
    },
    {
        "provider": "openai",
        "model": "openai/gpt-4.1",
        "label": "GPT-4.1",
        "tier": "$$",
        "description": "Strong tool calling, competitive pricing",
    },
    {
        "provider": "openai",
        "model": "openai/gpt-4o",
        "label": "GPT-4o",
        "tier": "$$$",
        "description": "Proven reliability, battle-tested",
    },
    {
        "provider": "anthropic",
        "model": "anthropic/claude-opus-4-20250514",
        "label": "Claude Opus 4",
        "tier": "$$$$",
        "description": "Maximum quality — complex multi-step deployments",
    },
]

APPROVED_MODEL_IDS: frozenset[str] = frozenset(m["model"] for m in APPROVED_MODELS)


def _parse_model_list(raw: str) -> list[str]:
    stripped = raw.strip()
    if not stripped:
        return []
    if stripped.startswith("["):
        try:
            return _json.loads(stripped)
        except _json.JSONDecodeError:
            return []
    return [m.strip() for m in stripped.split(",") if m.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ANSIBLEFORGE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ────────────────────────────────────────────────────────
    llm_provider: str = ""
    llm_model: str = ""
    llm_fallback_models_raw: str = Field(default="", alias="ANSIBLEFORGE_LLM_FALLBACK_MODELS")

    @property
    def llm_fallback_models(self) -> list[str]:
        return _parse_model_list(self.llm_fallback_models_raw)
    llm_compaction_model: str = "deepseek/deepseek-v4-flash"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 16384
    llm_max_context_tokens: int = 48000
    llm_model_context_window: int = 64000
    ollama_base_url: str = "http://localhost:11434"

    # Provider keys read without prefix so LiteLLM picks them up too
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")

    # ── Agent ──────────────────────────────────────────────────────
    max_agent_steps: int = 200
    session_timeout_seconds: int = 7200
    default_project_dir: Path = Path.home() / "tuyere-projects"

    @field_validator("default_project_dir", mode="before")
    @classmethod
    def _expand_default_project_dir(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return Path.home() / "tuyere-projects"
            return Path(v).expanduser()
        return v

    # ── API ────────────────────────────────────────────────────────
    api_key: str | None = None
    jwt_secret: str | None = None
    host: str = "127.0.0.1"
    port: int = 8420
    log_level: str = "info"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://localhost:8420",
            "http://127.0.0.1:8420",
            "tauri://localhost",
            "https://tauri.localhost",
        ]
    )


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

_RUNTIME_LLM_PATH = Path.home() / ".ansibleforge" / "llm_settings.json"


def _load_persisted_llm() -> RuntimeLLMConfig:
    """Load persisted LLM settings from disk if available."""
    try:
        if _RUNTIME_LLM_PATH.exists():
            import json
            data = json.loads(_RUNTIME_LLM_PATH.read_text(encoding="utf-8"))
            return RuntimeLLMConfig(**data)
    except Exception:
        pass
    return RuntimeLLMConfig()


def _persist_llm(config: RuntimeLLMConfig) -> None:
    """Save LLM settings to disk so they survive restarts."""
    try:
        import json
        _RUNTIME_LLM_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RUNTIME_LLM_PATH.write_text(
            json.dumps(config.model_dump(), indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


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
        _persist_llm(_runtime_llm)
    return _runtime_llm


def clear_runtime_llm() -> None:
    global _runtime_llm
    with _lock:
        _runtime_llm = RuntimeLLMConfig()
        _persist_llm(_runtime_llm)


def _init_runtime_llm() -> None:
    """Called at import time to restore persisted LLM settings."""
    global _runtime_llm
    _runtime_llm = _load_persisted_llm()


_init_runtime_llm()


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
