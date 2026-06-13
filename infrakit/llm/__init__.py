"""
infrakit.llm
------------
Unified async/sync LLM client with key rotation, quota tracking,
rate limiting, and batch processing.

Public API::

    from infrakit.llm import LLMClient, Prompt, QuotaConfig
    from infrakit.llm import LLMResponse, BatchResult
    from infrakit.llm.providers import OpenAIProvider, GeminiProvider
"""

from .client import LLMClient
from .models import (
    BatchResult,
    LLMResponse,
    Prompt,
    Provider,
    QuotaConfig,
    RequestMeta,
)
from .providers import GeminiProvider, GroqProvider, OpenAIProvider

__all__ = [
    "LLMClient",
    "Prompt",
    "QuotaConfig",
    "LLMResponse",
    "BatchResult",
    "RequestMeta",
    "Provider",
    "OpenAIProvider",
    "GeminiProvider",
    "GroqProvider",
]