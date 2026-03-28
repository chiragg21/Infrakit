"""
infrakit.llm.providers.base
---------------------------
Abstract base class that every provider must implement.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional, Type

from pydantic import BaseModel

from ..models import LLMResponse, Prompt


class BaseProvider(ABC):
    """
    All provider-specific logic (API call, token counting, error
    classification) lives in subclasses.  The client only talks to
    this interface.
    """

    # ── configuration ──────────────────────────────────────────────────────

    #: Override in subclass with a sensible default (e.g. "gpt-4o-mini").
    DEFAULT_MODEL: str = ""

    def __init__(self, model: Optional[str] = None) -> None:
        self.model = model or self.DEFAULT_MODEL

    # ── abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    async def async_generate(
        self,
        prompt: Prompt,
        api_key: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Async generate.  Must return an LLMResponse even on soft failures
        (schema mismatch).  Hard failures (network, auth) should raise.
        """

    @abstractmethod
    def sync_generate(
        self,
        prompt: Prompt,
        api_key: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: int = 2,
        **kwargs: Any,
    ) -> LLMResponse:
        """Sync wrapper around async_generate (or a native sync call)."""

    # ── helpers shared by subclasses ───────────────────────────────────────

    @staticmethod
    def _validate_schema(
        content: str,
        response_model: Type[BaseModel],
        retries: int,
    ) -> tuple[Optional[BaseModel], bool]:
        """
        Try to parse *content* as JSON and validate against *response_model*.

        Returns
        -------
        (parsed_instance, matched)
            matched is True on success, False after all retries exhausted.
        """
        import json

        for attempt in range(retries + 1):
            try:
                # strip common markdown fences
                text = content.strip()
                if text.startswith("```"):
                    lines = text.splitlines()
                    # drop first (```json) and last (```) lines
                    text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
                data = json.loads(text)
                instance = response_model.model_validate(data)
                return instance, True
            except Exception:
                if attempt == retries:
                    return None, False
        return None, False

    @staticmethod
    def _is_quota_error(exc: Exception) -> bool:
        """
        Return True if *exc* indicates a hard quota / auth failure
        (should deactivate the key, not retry).
        Subclasses may override for provider-specific error codes.
        """
        msg = str(exc).lower()
        return any(
            kw in msg
            for kw in (
                "quota",
                "rate_limit_exceeded",
                "billing",
                "insufficient_quota",
                "resource_exhausted",
                "invalid_api_key",
                "permission_denied",
            )
        )