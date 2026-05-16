"""LiteLLM-backed LLM client with multi-provider support, fallbacks, and streaming."""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx
import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from ansible_forge.config import Settings, get_runtime_llm, get_settings
from ansible_forge.logging import get_logger

logger = get_logger(__name__)

litellm.drop_params = True
litellm.modify_params = True

_LLM_HTTP_TIMEOUT = httpx.Timeout(connect=15, read=45, write=15, pool=30)


class LLMClient:
    """Unified LLM interface wrapping LiteLLM for tool-use agent workflows."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._configure_env()

    def _configure_env(self) -> None:
        if self._settings.openai_api_key:
            os.environ.setdefault("OPENAI_API_KEY", self._settings.openai_api_key)
        if self._settings.anthropic_api_key:
            os.environ.setdefault("ANTHROPIC_API_KEY", self._settings.anthropic_api_key)
        if self._settings.ollama_base_url:
            os.environ.setdefault("OLLAMA_API_BASE", self._settings.ollama_base_url)

    def _runtime_kwargs(self) -> dict[str, Any]:
        """Return per-call api_key / api_base kwargs instead of mutating os.environ."""
        rt = get_runtime_llm()
        result: dict[str, Any] = {}
        if rt.api_key and rt.provider:
            result["api_key"] = rt.api_key
        if rt.api_base:
            result["api_base"] = rt.api_base
        return result

    @staticmethod
    def _provider_env_key(provider: str) -> str | None:
        mapping: dict[str, str] = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "groq": "GROQ_API_KEY",
            "mistral": "MISTRAL_API_KEY",
            "cohere": "COHERE_API_KEY",
            "google": "GEMINI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "together_ai": "TOGETHERAI_API_KEY",
            "fireworks_ai": "FIREWORKS_AI_API_KEY",
            "perplexity": "PERPLEXITYAI_API_KEY",
            "openrouter": "OPENROUTER_API_KEY",
        }
        return mapping.get(provider.lower())

    def _effective_model(self) -> str:
        """Return the model string in provider/model format that LiteLLM expects."""
        rt = get_runtime_llm()
        model = rt.model if rt.model else self._settings.llm_model
        provider = rt.provider if rt.provider else self._settings.llm_provider

        if "/" not in model and provider:
            model = f"{provider}/{model}"

        return model

    def _effective_temperature(self) -> float:
        rt = get_runtime_llm()
        return rt.temperature if rt.temperature is not None else self._settings.llm_temperature

    def _effective_max_tokens(self) -> int:
        rt = get_runtime_llm()
        return rt.max_tokens if rt.max_tokens is not None else self._settings.llm_max_tokens

    @property
    def _model_chain(self) -> list[str]:
        return [self._effective_model(), *self._settings.llm_fallback_models]

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        """Send a chat completion request with optional tool definitions.

        Tries the primary model first, then falls back through the fallback chain.
        """
        model = model or self._effective_model()
        temperature = temperature if temperature is not None else self._effective_temperature()
        max_tokens = max_tokens or self._effective_max_tokens()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            **self._runtime_kwargs(),
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        response = await self._call_with_fallback(**kwargs)
        return LLMResponse.from_litellm(response)

    async def complete_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream a chat completion, yielding delta chunks."""
        model = model or self._effective_model()
        temperature = temperature if temperature is not None else self._effective_temperature()
        max_tokens = max_tokens or self._effective_max_tokens()

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self._runtime_kwargs(),
        }
        if tools:
            kwargs["tools"] = tools

        response = await self._stream_with_retry(**kwargs)
        async for chunk in response:
            choice = chunk.choices[0] if chunk.choices else None  # type: ignore[union-attr]
            if choice is None:
                usage = getattr(chunk, "usage", None)
                if usage:
                    yield {"usage": {
                        "prompt_tokens": usage.prompt_tokens or 0,
                        "completion_tokens": usage.completion_tokens or 0,
                        "total_tokens": usage.total_tokens or 0,
                    }}
                continue
            delta = choice.delta
            yield {
                "content": getattr(delta, "content", None),
                "reasoning_content": getattr(delta, "reasoning_content", None),
                "tool_calls": (
                    [tc.model_dump() for tc in delta.tool_calls]
                    if getattr(delta, "tool_calls", None)
                    else None
                ),
                "finish_reason": choice.finish_reason,
            }

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=75),
        retry=retry_if_exception_type((litellm.RateLimitError, litellm.ServiceUnavailableError)),
        reraise=True,
        before_sleep=lambda rs: logger.info(
            "stream_rate_limit_retry",
            attempt=rs.attempt_number,
            wait=f"{getattr(rs.next_action, 'sleep', 0):.1f}s",
        ),
    )
    async def _stream_with_retry(self, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", _LLM_HTTP_TIMEOUT)
        return await litellm.acompletion(**kwargs)

    async def _call_with_fallback(self, **kwargs: Any) -> Any:
        primary_model = kwargs.get("model", self._settings.llm_model)
        fallbacks = [m for m in self._model_chain if m != primary_model]

        last_error = ""
        try:
            return await self._single_call(**kwargs)
        except Exception as exc:
            last_error = str(exc)
            logger.warning("primary_model_failed", model=primary_model, error=last_error)
            for fallback_model in fallbacks:
                try:
                    logger.info("trying_fallback", model=fallback_model)
                    kwargs["model"] = fallback_model
                    return await self._single_call(**kwargs)
                except Exception as fb_exc:
                    last_error = str(fb_exc)
                    logger.warning("fallback_failed", model=fallback_model, error=last_error)
                    continue

            tried = [primary_model, *fallbacks] if fallbacks else [primary_model]
            raise RuntimeError(
                f"All models failed. Tried: {', '.join(tried)}. "
                f"Last error: {last_error}"
            ) from exc

    @retry(
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=2, min=2, max=75),
        retry=retry_if_exception_type((litellm.RateLimitError, litellm.ServiceUnavailableError)),
        reraise=True,
        before_sleep=lambda rs: logger.info(
            "rate_limit_retry",
            attempt=rs.attempt_number,
            wait=f"{getattr(rs.next_action, 'sleep', 0):.1f}s",
        ),
    )
    async def _single_call(self, **kwargs: Any) -> Any:
        kwargs.setdefault("timeout", _LLM_HTTP_TIMEOUT)
        try:
            return await litellm.acompletion(**kwargs)
        except (litellm.exceptions.APIConnectionError, litellm.exceptions.BadRequestError) as exc:
            error_msg = str(exc)
            if "max_output_tokens" in error_msg or "max_tokens" in error_msg:
                logger.warning("retrying_without_max_tokens", model=kwargs.get("model"))
                kwargs.pop("max_tokens", None)
                return await litellm.acompletion(**kwargs)
            raise


class ToolCall:
    """Represents a single tool call from the LLM."""

    def __init__(self, id: str, name: str, arguments: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.arguments = arguments

    def __repr__(self) -> str:
        return f"ToolCall(id={self.id!r}, name={self.name!r})"


def _repair_json(raw: str) -> dict[str, Any]:
    """Best-effort repair of truncated JSON from LLM tool call arguments."""
    s = raw.strip()
    # Close any open strings and braces
    if s.count('"') % 2 == 1:
        s += '"'
    open_braces = s.count("{") - s.count("}")
    open_brackets = s.count("[") - s.count("]")
    s += "]" * max(open_brackets, 0)
    s += "}" * max(open_braces, 0)
    try:
        return json.loads(s)  # type: ignore[no-any-return]
    except json.JSONDecodeError:
        return {"_raw_truncated": raw[:500]}


class LLMResponse:
    """Parsed response from a chat completion."""

    def __init__(
        self,
        content: str | None,
        tool_calls: list[ToolCall],
        finish_reason: str | None,
        usage: dict[str, int],
        raw: Any = None,
        reasoning_content: str | None = None,
    ) -> None:
        self.content = content
        self.tool_calls = tool_calls
        self.finish_reason = finish_reason
        self.usage = usage
        self.raw = raw
        self.reasoning_content = reasoning_content

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0

    @property
    def raw_message(self) -> Any:
        """Return the raw ChatCompletionMessage from the provider response.

        This preserves provider-specific fields (e.g. DeepSeek
        ``reasoning_content``) that would be stripped if we reconstructed
        the message from a plain dict.
        """
        if self.raw is None:
            return None
        try:
            return self.raw.choices[0].message
        except (IndexError, AttributeError):
            return None

    @classmethod
    def from_litellm(cls, response: Any) -> LLMResponse:
        choice = response.choices[0]
        message = choice.message

        tool_calls: list[ToolCall] = []
        if message.tool_calls:
            for tc in message.tool_calls:
                args = tc.function.arguments
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = _repair_json(args)
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage_info = {}
        if hasattr(response, "usage") and response.usage:
            usage_info = {
                "prompt_tokens": response.usage.prompt_tokens or 0,
                "completion_tokens": response.usage.completion_tokens or 0,
                "total_tokens": response.usage.total_tokens or 0,
            }

        reasoning = getattr(message, "reasoning_content", None)

        return cls(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            usage=usage_info,
            raw=response,
            reasoning_content=reasoning,
        )
