"""
infrakit.llm.providers.gemini
------------------------------
Gemini provider — wraps the google-generativeai Python SDK.

Install dependency::

    pip install google-genai

Supported models (default): gemini-2.5-flash
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..models import LLMResponse, Prompt
from .base import BaseProvider


class GeminiProvider(BaseProvider):
    """
    Provider for Google's Gemini generative models.

    Parameters
    ----------
    model       Model string to use. Defaults to ``gemini-1.5-flash``.
    """

    DEFAULT_MODEL = "gemini-2.5-flash"
    PROVIDER_NAME = "gemini"

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
        """
        Async generate using google-generativeai.

        The SDK's generate_content is synchronous; we run it in a thread
        executor to avoid blocking the event loop.
        """
        loop = asyncio.get_event_loop()
        t0 = time.perf_counter()

        result = await loop.run_in_executor(
            None,
            lambda: self._sync_call(prompt, api_key, **kwargs),
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return self._build_response(result, latency_ms, response_model, schema_retries, api_key)

    def sync_generate(
        self,
        prompt: Prompt,
        api_key: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResponse:
        """Sync generate — direct SDK call."""
        t0 = time.perf_counter()
        result = self._sync_call(prompt, api_key, **kwargs)
        latency_ms = (time.perf_counter() - t0) * 1000
        return self._build_response(result, latency_ms, response_model, schema_retries, api_key)

    # ── internal helpers ───────────────────────────────────────────────────

    def _sync_call(self, prompt: Prompt, api_key: str, **kwargs: Any) -> Any:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)

        # The new SDK uses a config object for arguments like system instructions,
        # temperature, etc. We map your kwargs directly into it.
        config_args = kwargs.copy()
        if prompt.system:
            config_args["system_instruction"] = prompt.system

        config = types.GenerateContentConfig(**config_args) if config_args else None

        response = client.models.generate_content(
            model=self.model,
            contents=prompt.user,
            config=config,
        )
        return response

    def _build_response(
        self,
        response: Any,
        latency_ms: float,
        response_model: Optional[Type[BaseModel]],
        schema_retries: int,
        api_key: str,
    ) -> LLMResponse:
        # Extract text
        try:
            content = response.text or ""
        except Exception:
            content = ""

        # Token counts — available in usage_metadata (may be None on some models)
        usage = getattr(response, "usage_metadata", None)
        input_tokens = getattr(usage, "prompt_token_count", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        total_tokens = getattr(usage, "total_token_count", 0) or (input_tokens + output_tokens)

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
            from google import genai  # noqa: F401
        except ImportError as exc:
            raise ImportError(
                "google-genai package is required for GeminiProvider. "
                "Install it with: pip install google-genai"
            ) from exc

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """Gemini-specific quota/auth error detection."""
        # Handle the new SDK's APIError exception
        if exc.__class__.__name__ == "APIError":
            code = getattr(exc, "code", None)
            # 429: Resource Exhausted, 403: Permission Denied, 401: Unauthenticated
            if code in (429, 403, 401):
                return True
        return BaseProvider._is_quota_error(exc)