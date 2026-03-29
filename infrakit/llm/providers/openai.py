"""
infrakit.llm.providers.openai
------------------------------
OpenAI provider — wraps the openai Python SDK.

Install dependency::

    pip install openai

Supported models (default): gpt-4o-mini
"""

from __future__ import annotations

import time
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..models import LLMResponse, Prompt
from .base import BaseProvider


class OpenAIProvider(BaseProvider):
    """
    Provider for OpenAI's Chat Completions API.

    Parameters
    ----------
    model       Model string to use. Defaults to ``gpt-4o-mini``.
    """

    DEFAULT_MODEL = "gpt-4o-mini"
    PROVIDER_NAME = "openai"

    def __init__(self, model: Optional[str] = None) -> None:
        super().__init__(model)
        self._check_sdk()

    # ── public interface ───────────────────────────────────────────────────

    async def async_generate(
        self,
        prompt: Prompt,
        api_key: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async generate using openai.AsyncOpenAI."""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=api_key)
        messages = self._build_messages(prompt)
        t0 = time.perf_counter()

        response = await client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )

        latency_ms = (time.perf_counter() - t0) * 1000
        return self._build_response(response, latency_ms, response_model, schema_retries, api_key)

    def sync_generate(
        self,
        prompt: Prompt,
        api_key: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Sync generate using openai.OpenAI (the blocking SDK client).

        Deliberately does NOT use asyncio.run() so it is safe to call from:
        - threads (threaded batch mode)
        - environments with a running event loop (Jupyter, FastAPI, etc.)
        - Windows, where asyncio loop/thread interactions are more restrictive
        """
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        messages = self._build_messages(prompt)
        t0 = time.perf_counter()

        response = client.chat.completions.create(
            model=self.model,
            messages=messages,
            **kwargs,
        )

        latency_ms = (time.perf_counter() - t0) * 1000
        return self._build_response(response, latency_ms, response_model, schema_retries, api_key)

    # ── internal helpers ───────────────────────────────────────────────────

    @staticmethod
    def _build_messages(prompt: Prompt) -> list[dict]:
        messages = []
        if prompt.system:
            messages.append({"role": "system", "content": prompt.system})
        messages.append({"role": "user", "content": prompt.user})
        return messages

    def _build_response(
        self,
        response: Any,
        latency_ms: float,
        response_model: Optional[Type[BaseModel]],
        schema_retries: int,
        api_key: str,
    ) -> LLMResponse:
        choice = response.choices[0]
        content = choice.message.content or ""

        usage = response.usage
        input_tokens = usage.prompt_tokens if usage else 0
        output_tokens = usage.completion_tokens if usage else 0
        total_tokens = usage.total_tokens if usage else 0

        parsed = None
        schema_matched = False

        if response_model is not None:
            parsed, schema_matched = self._validate_schema(
                content, response_model, schema_retries
            )

        return LLMResponse(
            content=content,
            parsed=parsed,
            schema_matched=schema_matched,
            provider=self.PROVIDER_NAME,
            model=self.model,
            key_id=api_key[:8],
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _check_sdk() -> None:
        try:
            import openai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "openai package is required for OpenAIProvider. "
                "Install it with: pip install openai"
            ) from exc

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """OpenAI-specific quota/auth HTTP status codes."""
        try:
            from openai import APIStatusError
            if isinstance(exc, APIStatusError):
                # 401 invalid key, 402 billing, 429 with quota message
                if exc.status_code in (401, 402):
                    return True
                if exc.status_code == 429:
                    msg = str(exc).lower()
                    return "quota" in msg or "billing" in msg
        except ImportError:
            pass
        return BaseProvider._is_quota_error(exc)