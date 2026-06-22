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
        "provider": "zai",
        "model": "zai/glm-5.2",
        "label": "GLM-5.2 (Z.AI)",
        "tier": "$$",
        "description": "Z.AI flagship — 1M context, strong long-horizon coding & tool calling",
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


def _normalize_container_runtime_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    leaf = Path(text).name.lower()
    if leaf.endswith(".exe"):
        leaf = leaf[:-4]
    if leaf in ("docker", "podman"):
        return leaf
    return None


def _normalize_host_mode_value(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ("local", "remote"):
        return text
    return None


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
    zai_api_key: str | None = Field(default=None, alias="ZAI_API_KEY")

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

    # ── Execution Environment ─────────────────────────────────────
    ee_enabled: bool = False
    ee_image: str = "avijra28/tuyere-ee:latest"
    ee_container_runtime: str = "docker"
    ee_host_mode: str = "local"
    ee_remote_host: str | None = None
    ee_remote_workspace_root: str = "/var/lib/tuyere/workspaces"

    @field_validator("ee_container_runtime", mode="before")
    @classmethod
    def _normalize_ee_container_runtime(cls, v: Any) -> str:
        normalized = _normalize_container_runtime_value(v)
        return normalized or "docker"

    @field_validator("ee_host_mode", mode="before")
    @classmethod
    def _normalize_ee_host_mode(cls, v: Any) -> str:
        normalized = _normalize_host_mode_value(v)
        return normalized or "local"

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


class RuntimeEEConfig(BaseModel):
    """Mutable EE configuration that can be changed at runtime via the API."""

    enabled: bool | None = None
    image: str | None = None
    container_runtime: str | None = None
    host_mode: str | None = None
    remote_host: str | None = None
    remote_workspace_root: str | None = None

    @field_validator("container_runtime", mode="before")
    @classmethod
    def _normalize_container_runtime(cls, v: Any) -> str | None:
        return _normalize_container_runtime_value(v)

    @field_validator("host_mode", mode="before")
    @classmethod
    def _normalize_host_mode(cls, v: Any) -> str | None:
        return _normalize_host_mode_value(v)


_settings: Settings | None = None
_runtime_llm = RuntimeLLMConfig()
_runtime_ee = RuntimeEEConfig()
_lock = threading.Lock()

_RUNTIME_LLM_PATH = Path.home() / ".ansibleforge" / "llm_settings.json"
_RUNTIME_EE_PATH = Path.home() / ".ansibleforge" / "ee_settings.json"


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


def _load_persisted_ee() -> RuntimeEEConfig:
    try:
        if _RUNTIME_EE_PATH.exists():
            import json
            data = json.loads(_RUNTIME_EE_PATH.read_text(encoding="utf-8"))
            return RuntimeEEConfig(**data)
    except Exception:
        pass
    return RuntimeEEConfig()


def _persist_ee(config: RuntimeEEConfig) -> None:
    try:
        import json
        _RUNTIME_EE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RUNTIME_EE_PATH.write_text(
            json.dumps(config.model_dump(), indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def get_runtime_ee() -> RuntimeEEConfig:
    return _runtime_ee


def update_runtime_ee(patch: dict[str, Any]) -> RuntimeEEConfig:
    global _runtime_ee
    with _lock:
        current = _runtime_ee.model_dump()
        current.update({k: v for k, v in patch.items() if v is not None})
        _runtime_ee = RuntimeEEConfig(**current)
        _persist_ee(_runtime_ee)
    return _runtime_ee


def clear_runtime_ee() -> None:
    global _runtime_ee
    with _lock:
        _runtime_ee = RuntimeEEConfig()
        _persist_ee(_runtime_ee)


def _init_runtime_ee() -> None:
    global _runtime_ee
    _runtime_ee = _load_persisted_ee()


_init_runtime_ee()


def effective_ee_enabled() -> bool:
    rt = get_runtime_ee()
    if rt.enabled is not None:
        return rt.enabled
    return get_settings().ee_enabled


def effective_ee_image() -> str:
    rt = get_runtime_ee()
    if rt.image:
        return rt.image
    return get_settings().ee_image


def effective_ee_container_runtime() -> str:
    rt = get_runtime_ee()
    if rt.container_runtime:
        return rt.container_runtime
    return get_settings().ee_container_runtime


def effective_ee_host_mode() -> str:
    rt = get_runtime_ee()
    if rt.host_mode:
        return rt.host_mode
    return get_settings().ee_host_mode


def effective_ee_remote_host() -> str | None:
    rt = get_runtime_ee()
    if rt.remote_host:
        return rt.remote_host
    return get_settings().ee_remote_host


def effective_ee_remote_workspace_root() -> str:
    rt = get_runtime_ee()
    if rt.remote_workspace_root:
        return rt.remote_workspace_root
    return get_settings().ee_remote_workspace_root


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
