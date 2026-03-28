"""
infrakit.llm.models
-------------------
Shared data structures for the LLM subsystem.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional, Type

from pydantic import BaseModel


# ── enums ──────────────────────────────────────────────────────────────────

class Provider(str, Enum):
    OPENAI = "openai"
    GEMINI = "gemini"


class KeyStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"   # quota exhausted — auto-reactivates after reset


# ── prompt input ───────────────────────────────────────────────────────────

@dataclass
class Prompt:
    """
    Represents a single LLM prompt.

    Usage::

        # combined prompt
        Prompt(user="Tell me about Python.")

        # system + user split
        Prompt(system="You are a helpful assistant.", user="Tell me about Python.")
    """
    user: str
    system: Optional[str] = None


# ── response ───────────────────────────────────────────────────────────────

@dataclass
class LLMResponse:
    """
    Returned by every generate() call.

    Attributes
    ----------
    content         Raw text from the model.
    parsed          Populated when a response_model is given and validation
                    succeeds; None otherwise.
    schema_matched  True if parsed is not None. False means validation failed
                    after all retries — content still contains the raw reply.
    provider        Which provider handled this request.
    model           Model string used (e.g. "gpt-4o-mini").
    key_id          Truncated key identifier (first 8 chars).
    input_tokens    Prompt token count.
    output_tokens   Completion token count.
    total_tokens    input + output.
    latency_ms      Wall-clock time for the API call in milliseconds.
    error           Set when the request ultimately failed.
    """
    content: str
    parsed: Optional[Any]
    schema_matched: bool
    provider: str
    model: str
    key_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    latency_ms: float
    error: Optional[str] = None


# ── request metadata (stored for transparency) ────────────────────────────

@dataclass
class RequestMeta:
    """
    Lightweight record of one API call. Stored in the key manager's
    rolling window — NO prompt/response content is kept here.
    """
    timestamp: float = field(default_factory=time.time)
    provider: str = ""
    key_id: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    success: bool = True
    error: Optional[str] = None


# ── quota config ───────────────────────────────────────────────────────────

@dataclass
class QuotaConfig:
    """
    Manual quota limits for a single API key.

    All fields are optional. Only the fields you set are enforced.

    Parameters
    ----------
    rpm_limit       Max requests per minute.
    tpm_limit       Max tokens per minute.
    daily_token_limit  Max tokens per calendar day.
    reset_hour_utc  Hour (0-23 UTC) at which the daily quota resets.
                    Defaults to 0 (midnight UTC).
    """
    rpm_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    daily_token_limit: Optional[int] = None
    reset_hour_utc: int = 0


# ── batch result ───────────────────────────────────────────────────────────

@dataclass
class BatchResult:
    """
    Container for a batch generate() call. Results are in the same
    order as the input prompts.
    """
    results: list[Optional[LLMResponse]]
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    total_latency_ms: float
    success_count: int
    failure_count: int