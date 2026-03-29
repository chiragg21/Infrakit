"""
infrakit.llm.client
--------------------
LLMClient — the single entry point for all LLM interactions.

Quick start::

    from infrakit.llm import LLMClient, Prompt
    from pydantic import BaseModel

    client = LLMClient(
        keys={"openai_keys": ["sk-..."], "gemini_keys": ["AIza..."]},
        storage_dir="./logs",
    )

    # simple generate
    response = client.generate(Prompt(user="What is 2+2?"), provider="openai")
    print(response.content)

    # structured output
    class Answer(BaseModel):
        value: int
        explanation: str

    response = client.generate(
        Prompt(system="Be concise.", user="What is 2+2?"),
        provider="openai",
        response_model=Answer,
    )
    if response.schema_matched:
        print(response.parsed.value)

    # batch
    prompts = [Prompt(user=f"Translate '{w}' to French") for w in ["cat", "dog", "bird"]]
    batch = client.batch_generate(prompts, provider="gemini")
    for r in batch.results:
        print(r.content)
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, Literal, Optional, Type

from pydantic import BaseModel

from .batch import async_batch, threaded_batch


def _run_async(coro):
    """
    Run an async coroutine from sync code, safely.

    - If there is no running event loop (normal script / CLI):
      use asyncio.run() directly.
    - If there IS a running loop (Jupyter, FastAPI, nested asyncio):
      spin up a new loop in a background thread and block until done.
      This avoids the "asyncio.run() cannot be called from a running
      event loop" error without requiring the caller to be async.
    """
    import concurrent.futures

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(coro)

    # Running inside an existing loop — use a thread with its own loop
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(asyncio.run, coro)
        return future.result()


from .key_manager import KeyManager
from .models import BatchResult, LLMResponse, Prompt, Provider, QuotaConfig, RequestMeta
from .providers.base import BaseProvider
from .providers.gemini import GeminiProvider
from .providers.openai import OpenAIProvider
from .rate_limiter import RateLimiter


# ── defaults ───────────────────────────────────────────────────────────────

_DEFAULT_MAX_CONCURRENT = 3
_DEFAULT_KEY_RETRIES = 2      # retry same key N times before rotating
_DEFAULT_SCHEMA_RETRIES = 2   # attempts to parse structured output
_DEFAULT_META_WINDOW = 50     # recent request metadata records per key


class LLMClient:
    """
    Unified client for OpenAI and Gemini.

    Parameters
    ----------
    keys            API keys dict::

                        {
                            "openai_keys": ["sk-key1", "sk-key2"],
                            "gemini_keys": ["AIza-key1"],
                        }

    storage_dir     Path to a folder where key state is persisted.
                    Defaults to ``~/.infrakit/llm/`` if not given.
    mode            ``"async"`` — asyncio + semaphore concurrency.
                    ``"threaded"`` — ThreadPoolExecutor concurrency.
                    Default: ``"async"``.
    max_concurrent  Max simultaneous in-flight requests for batch calls.
                    Default: 3.
    key_retries     How many times to retry the *same* key on a transient
                    error before rotating to the next one.  Default: 2.
    schema_retries  How many times to retry JSON parsing/validation before
                    giving up and returning schema_matched=False.  Default: 2.
    meta_window     How many recent request metadata records to keep per key.
                    Default: 50.
    openai_model    Default OpenAI model.  Default: ``"gpt-4o-mini"``.
    gemini_model    Default Gemini model.  Default: ``"gemini-1.5-flash"``.
    show_progress   Show tqdm progress bar during batch calls.  Default: True.
    """

    def __init__(
        self,
        keys: dict[str, list[str]],
        storage_dir: Optional[str | Path] = None,
        quota_file: Optional[str | Path] = None,
        mode: Literal["async", "threaded"] = "async",
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
        key_retries: int = _DEFAULT_KEY_RETRIES,
        schema_retries: int = _DEFAULT_SCHEMA_RETRIES,
        meta_window: int = _DEFAULT_META_WINDOW,
        openai_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
        show_progress: bool = True,
    ) -> None:
        self._mode = mode
        self._max_concurrent = max_concurrent
        self._key_retries = key_retries
        self._schema_retries = schema_retries
        self._show_progress = show_progress

        # Key manager (persistence, rotation, quota)
        self._km = KeyManager(
            keys=keys,
            storage_dir=storage_dir,
            quota_file=quota_file,
            meta_window=meta_window,
        )

        # Rate limiter (RPM/TPM gating)
        self._rl = RateLimiter(self._km)

        # Providers
        self._providers: dict[str, BaseProvider] = {
            Provider.OPENAI: OpenAIProvider(model=openai_model),
            Provider.GEMINI: GeminiProvider(model=gemini_model),
        }

    # ── public: single generate ────────────────────────────────────────────

    def generate(
        self,
        prompt: Prompt,
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """
        Generate a response for a single prompt (blocking).

        Always uses the sync code path so it is safe to call from any context:
        scripts, threads, Jupyter, FastAPI handlers, Windows, etc.

        If you are inside an async function use ``await async_generate()``
        instead; that path uses the async SDK clients end-to-end.

        Handles key rotation, RPM waiting, retries, and metadata recording.
        Always returns an LLMResponse — check ``.error`` for failures.
        """
        return self._sync_single_generate(
            prompt=prompt,
            response_model=response_model,
            provider=provider,
            **kwargs,
        )

    async def async_generate(
        self,
        prompt: Prompt,
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Async version of generate() — await this inside an async context."""
        return await self._async_single_generate(
            prompt=prompt,
            response_model=response_model,
            provider=provider,
            **kwargs,
        )

    # ── public: batch generate ─────────────────────────────────────────────

    def batch_generate(
        self,
        prompts: list[Prompt],
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        max_concurrent: Optional[int] = None,
        show_progress: Optional[bool] = None,
        **kwargs: Any,
    ) -> BatchResult:
        """
        Generate responses for a list of prompts.

        Results are in the same order as *prompts*.
        Uses async or threaded mode based on client ``mode`` setting.

        Parameters
        ----------
        prompts         List of Prompt objects.
        provider        ``"openai"`` or ``"gemini"``.
        response_model  Optional Pydantic model for structured output.
        max_concurrent  Override per-call concurrency limit.
        show_progress   Override per-call progress bar setting.
        """
        concurrency = max_concurrent or self._max_concurrent
        progress = show_progress if show_progress is not None else self._show_progress

        if self._mode == "async":
            return _run_async(
                async_batch(
                    generate_fn=self._async_single_generate,
                    prompts=prompts,
                    response_model=response_model,
                    schema_retries=self._schema_retries,
                    provider=provider,
                    max_concurrent=concurrency,
                    show_progress=progress,
                    extra_kwargs=kwargs,
                )
            )
        else:
            return threaded_batch(
                generate_fn=self._sync_single_generate,
                prompts=prompts,
                response_model=response_model,
                schema_retries=self._schema_retries,
                provider=provider,
                max_concurrent=concurrency,
                show_progress=progress,
                extra_kwargs=kwargs,
            )

    async def async_batch_generate(
        self,
        prompts: list[Prompt],
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        max_concurrent: Optional[int] = None,
        show_progress: Optional[bool] = None,
        **kwargs: Any,
    ) -> BatchResult:
        """Async version of batch_generate() for use inside async contexts."""
        concurrency = max_concurrent or self._max_concurrent
        progress = show_progress if show_progress is not None else self._show_progress

        return await async_batch(
            generate_fn=self._async_single_generate,
            prompts=prompts,
            response_model=response_model,
            schema_retries=self._schema_retries,
            provider=provider,
            max_concurrent=concurrency,
            show_progress=progress,
            extra_kwargs=kwargs,
        )

    # ── public: quota management ───────────────────────────────────────────

    def set_quota(self, provider: str, key_id: str, quota: QuotaConfig) -> None:
        """
        Set or update quota limits for a specific key.

        ``quota.model`` controls scope:
          - ``None``  (default) — applies to all models on this key that
            don't have their own explicit entry.
          - A model string — applies only to that model.

        Examples::

            # key-level RPM + default daily limit for all models
            client.set_quota(
                provider="gemini",
                key_id="AIza-abc1",
                quota=QuotaConfig(rpm_limit=15, daily_token_limit=1_500_000),
            )

            # tighter limit for one expensive model only
            client.set_quota(
                provider="gemini",
                key_id="AIza-abc1",
                quota=QuotaConfig(model="gemini-2.5-pro", daily_token_limit=250_000),
            )
        """
        self._km.set_quota(provider, key_id, quota)

    def status(
        self,
        provider: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Return key status dicts.

        Parameters
        ----------
        provider    Filter to a specific provider (``"openai"`` / ``"gemini"``).
                    None returns all providers.
        key_id      Filter to a specific key (first 8 chars of the key).
                    None returns all keys for the provider.
        """
        return self._km.status_report(provider=provider, key_id=key_id)

    def print_status(
        self,
        provider: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> None:
        """Pretty-print key status to stdout (model-aware)."""
        import datetime
        rows = self._km.status_report(provider=provider, key_id=key_id)
        if not rows:
            print("No keys found.")
            return

        sep = "-" * 72
        for r in rows:
            print(sep)
            print(f"  Provider : {r['provider']}")
            print(f"  Key ID   : {r['key_id']}...")
            print(f"  Status   : {r['status']}")
            print(f"  RPM limit: {r['rpm_limit'] or 'not set'}  |  "
                  f"Current RPM: {r['current_rpm']}")
            print()

            models = r.get("models", [])
            if models:
                print(f"  Models ({len(models)} tracked)")
                for mr in models:
                    status_flag = "\u2713" if mr["status"] == "active" else "\u2717"
                    print(f"    [{status_flag}] {mr['model']}")
                    if mr["deactivated_at"]:
                        dt = datetime.datetime.utcfromtimestamp(mr["deactivated_at"])
                        print(f"        Deactivated : {dt.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                    print(f"        TPM limit   : {mr['tpm_limit'] or 'not set'}  "
                          f"Current TPM: {mr['current_tpm']}")
                    daily_rem = mr["daily_remaining"]
                    print(f"        Daily limit : {mr['daily_token_limit'] or 'not set'}  "
                          f"Used: {mr['day_token_total']}  "
                          f"Remaining: {daily_rem if daily_rem is not None else 'unlimited'}")
                    print(f"        Reset hour  : {mr['reset_hour_utc']:02d}:00 UTC")
                    print(f"        Totals      : {mr['total_requests']} req  "
                          f"{mr['total_tokens']} tok  {mr['total_errors']} err")
            else:
                print("  No model usage recorded yet.")

            if r["recent_meta"]:
                print()
                print(f"  Last {len(r['recent_meta'])} requests")
                for m in r["recent_meta"]:
                    ts = datetime.datetime.utcfromtimestamp(m["timestamp"])
                    status_str = "ok" if m["success"] else f"ERR: {m.get('error', '')[:60]}"
                    print(
                        f"    {ts.strftime('%H:%M:%S')} UTC | "
                        f"{m['model']:<28} | "
                        f"in={m['input_tokens']} out={m['output_tokens']} "
                        f"total={m['total_tokens']} | "
                        f"{m['latency_ms']:.0f}ms | {status_str}"
                    )
        print(sep)

    # ── internal: async single generate ───────────────────────────────────

    async def _async_single_generate(
        self,
        prompt: Prompt,
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        schema_retries = schema_retries if schema_retries is not None else self._schema_retries
        prov_impl = self._get_provider(provider)

        last_error: Optional[str] = None
        keys_tried: set[tuple] = set()

        while True:
            # acquire a key that has this model active
            try:
                raw_key, ks = self._km.get_key(provider, model=prov_impl.model)
            except RuntimeError as exc:
                return self._error_response(provider, str(exc))

            # avoid re-trying the same (key, model) combination
            if (ks.key_hash, prov_impl.model) in keys_tried:
                break

            # wait for RPM slot (key-level) and TPM slot (model-level)
            await self._rl.async_wait_for_slot(ks, prov_impl.model)

            # attempt with retries on same key
            for attempt in range(self._key_retries + 1):
                t0 = time.perf_counter()
                try:
                    response = await prov_impl.async_generate(
                        prompt=prompt,
                        api_key=raw_key,
                        response_model=response_model,
                        schema_retries=schema_retries,
                        **kwargs,
                    )
                    # success — record metadata
                    meta = RequestMeta(
                        provider=provider,
                        key_id=ks.key_id,
                        model=prov_impl.model,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens,
                        latency_ms=response.latency_ms,
                        success=True,
                    )
                    self._km.record_request(ks, meta)
                    return response

                except Exception as exc:
                    latency_ms = (time.perf_counter() - t0) * 1000
                    last_error = str(exc)
                    is_quota = prov_impl._is_quota_error(exc)

                    # record failed request
                    meta = RequestMeta(
                        provider=provider,
                        key_id=ks.key_id,
                        model=prov_impl.model,
                        latency_ms=latency_ms,
                        success=False,
                        error=last_error[:200],
                    )
                    self._km.record_request(ks, meta)

                    if is_quota:
                        # deactivate only this model on this key, not the whole key
                        self._km.deactivate_model(
                            ks, model=prov_impl.model, reason=last_error[:100]
                        )
                        break  # rotate to next key/model
                    if attempt < self._key_retries:
                        # small backoff before same-key retry
                        await asyncio.sleep(1.0 * (attempt + 1))
                    # else: fall through and rotate key

            keys_tried.add((ks.key_hash, prov_impl.model))

        return self._error_response(provider, last_error or "All keys exhausted.")

    # ── internal: sync single generate ────────────────────────────────────

    def _sync_single_generate(
        self,
        prompt: Prompt,
        provider: str,
        response_model: Optional[Type[BaseModel]] = None,
        schema_retries: Optional[int] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        schema_retries = schema_retries if schema_retries is not None else self._schema_retries
        prov_impl = self._get_provider(provider)

        last_error: Optional[str] = None
        keys_tried: set[tuple] = set()

        while True:
            try:
                raw_key, ks = self._km.get_key(provider, model=prov_impl.model)
            except RuntimeError as exc:
                return self._error_response(provider, str(exc))

            if (ks.key_hash, prov_impl.model) in keys_tried:
                break

            self._rl.sync_wait_for_slot(ks, prov_impl.model)

            for attempt in range(self._key_retries + 1):
                t0 = time.perf_counter()
                try:
                    response = prov_impl.sync_generate(
                        prompt=prompt,
                        api_key=raw_key,
                        response_model=response_model,
                        schema_retries=schema_retries,
                        **kwargs,
                    )
                    meta = RequestMeta(
                        provider=provider,
                        key_id=ks.key_id,
                        model=prov_impl.model,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens,
                        latency_ms=response.latency_ms,
                        success=True,
                    )
                    self._km.record_request(ks, meta)
                    return response

                except Exception as exc:
                    latency_ms = (time.perf_counter() - t0) * 1000
                    last_error = str(exc)
                    is_quota = prov_impl._is_quota_error(exc)

                    meta = RequestMeta(
                        provider=provider,
                        key_id=ks.key_id,
                        model=prov_impl.model,
                        latency_ms=latency_ms,
                        success=False,
                        error=last_error[:200],
                    )
                    self._km.record_request(ks, meta)

                    if is_quota:
                        self._km.deactivate_model(
                            ks, model=prov_impl.model, reason=last_error[:100]
                        )
                        break
                    if attempt < self._key_retries:
                        time.sleep(1.0 * (attempt + 1))

            keys_tried.add((ks.key_hash, prov_impl.model))

        return self._error_response(provider, last_error or "All keys exhausted.")

    # ── internal helpers ───────────────────────────────────────────────────

    def _get_provider(self, provider: str) -> BaseProvider:
        impl = self._providers.get(provider)
        if impl is None:
            raise ValueError(
                f"Unknown provider '{provider}'. "
                f"Valid options: {list(self._providers.keys())}"
            )
        return impl

    @staticmethod
    def _error_response(provider: str, error: str) -> LLMResponse:
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