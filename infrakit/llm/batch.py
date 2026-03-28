"""
infrakit.llm.batch
------------------
Batch processing engine for multiple prompts.

Two modes (chosen at LLMClient init):
  - async   : asyncio with a semaphore-based concurrency cap
  - threaded: concurrent.futures.ThreadPoolExecutor

Results are always returned in input order.
Progress bar via tqdm (optional — gracefully degrades if not installed).
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional, Type

from pydantic import BaseModel

from .models import BatchResult, LLMResponse, Prompt

try:
    from tqdm import tqdm as _tqdm
    from tqdm.asyncio import tqdm as _async_tqdm
    _HAS_TQDM = True
except ImportError:
    _HAS_TQDM = False


# ── async batch ────────────────────────────────────────────────────────────

async def async_batch(
    generate_fn: Callable[..., Any],          # LLMClient._async_single_generate
    prompts: list[Prompt],
    response_model: Optional[Type[BaseModel]],
    schema_retries: int,
    provider: str,
    max_concurrent: int,
    show_progress: bool,
    extra_kwargs: dict,
) -> BatchResult:
    """
    Run *generate_fn* over all prompts with bounded concurrency.
    Returns results in the same order as prompts.
    """
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[Optional[LLMResponse]] = [None] * len(prompts)

    async def _run(idx: int, prompt: Prompt) -> None:
        async with semaphore:
            try:
                result = await generate_fn(
                    prompt=prompt,
                    response_model=response_model,
                    schema_retries=schema_retries,
                    provider=provider,
                    **extra_kwargs,
                )
            except Exception as exc:
                result = _error_response(prompt, provider, str(exc))
            results[idx] = result

    tasks = [_run(i, p) for i, p in enumerate(prompts)]

    if show_progress and _HAS_TQDM:
        await _async_tqdm.gather(*tasks, desc="Batch", total=len(tasks), unit="prompt")
    else:
        if show_progress and not _HAS_TQDM:
            print("[infrakit.llm] tqdm not installed — install it for progress bars.")
        await asyncio.gather(*tasks)

    return _aggregate(results)


# ── threaded batch ─────────────────────────────────────────────────────────

def threaded_batch(
    generate_fn: Callable[..., Any],          # LLMClient._sync_single_generate
    prompts: list[Prompt],
    response_model: Optional[Type[BaseModel]],
    schema_retries: int,
    provider: str,
    max_concurrent: int,
    show_progress: bool,
    extra_kwargs: dict,
) -> BatchResult:
    """
    Run *generate_fn* over all prompts using a thread pool.
    Returns results in the same order as prompts.
    """
    results: list[Optional[LLMResponse]] = [None] * len(prompts)
    futures_map: dict[Any, int] = {}

    bar = None
    if show_progress:
        if _HAS_TQDM:
            bar = _tqdm(total=len(prompts), desc="Batch", unit="prompt")
        else:
            print("[infrakit.llm] tqdm not installed — install it for progress bars.")

    with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
        for idx, prompt in enumerate(prompts):
            future = executor.submit(
                generate_fn,
                prompt=prompt,
                response_model=response_model,
                schema_retries=schema_retries,
                provider=provider,
                **extra_kwargs,
            )
            futures_map[future] = idx

        for future in as_completed(futures_map):
            idx = futures_map[future]
            try:
                results[idx] = future.result()
            except Exception as exc:
                results[idx] = _error_response(prompts[idx], provider, str(exc))
            if bar:
                bar.update(1)

    if bar:
        bar.close()

    return _aggregate(results)


# ── helpers ────────────────────────────────────────────────────────────────

def _error_response(prompt: Prompt, provider: str, error: str) -> LLMResponse:
    return LLMResponse(
        content="",
        parsed=None,
        schema_matched=False,
        provider=provider,
        model="",
        key_id="",
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        latency_ms=0.0,
        error=error,
    )


def _aggregate(results: list[Optional[LLMResponse]]) -> BatchResult:
    total_in = sum(r.input_tokens for r in results if r)
    total_out = sum(r.output_tokens for r in results if r)
    total_tok = sum(r.total_tokens for r in results if r)
    total_lat = sum(r.latency_ms for r in results if r)
    success = sum(1 for r in results if r and not r.error)
    failure = sum(1 for r in results if r and r.error)

    return BatchResult(
        results=results,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_tokens=total_tok,
        total_latency_ms=total_lat,
        success_count=success,
        failure_count=failure,
    )