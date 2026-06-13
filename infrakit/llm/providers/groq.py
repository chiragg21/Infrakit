"""
infrakit.llm.providers.groq
-----------------------------
Groq provider — wraps the groq Python SDK.

Install dependency::

    pip install groq

Supported models (default): llama-3.3-70b-versatile
"""

from __future__ import annotations

import time
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..models import LLMResponse, Prompt
from .base import BaseProvider


class GroqProvider(BaseProvider):
    """
    Provider for Groq's Chat Completions API.

    Parameters
    ----------
    model       Model string to use. Defaults to ``llama-3.3-70b-versatile``.
    """

    DEFAULT_MODEL = "llama-3.3-70b-versatile"
    PROVIDER_NAME = "groq"

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
        """Async generate using groq.AsyncGroq."""
        from groq import AsyncGroq

        client = AsyncGroq(api_key=api_key)
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
        """Sync generate using groq.Groq (the blocking SDK client)."""
        from groq import Groq

        client = Groq(api_key=api_key)
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
            import groq  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "groq package is required for GroqProvider. "
                "Install it with: pip install groq"
            ) from exc

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """
        Groq-specific quota/auth HTTP status codes.

        429 with "rate_limit_exceeded" is *transient* (burst limit) and should
        be retried with backoff — NOT treated as a permanent quota exhaustion.
        Only 401/402 and 429 with "quota" or "billing" in the message warrant
        immediate model deactivation.
        """
        try:
            from groq import APIStatusError
            if isinstance(exc, APIStatusError):
                if exc.status_code in (401, 402):
                    return True
                if exc.status_code == 429:
                    msg = str(exc).lower()
                    return "quota" in msg or "billing" in msg
        except ImportError:
            pass
        return BaseProvider._is_quota_error(exc)
