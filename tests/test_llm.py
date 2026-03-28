"""
tests/test_llm.py
-----------------
Unit tests for infrakit.llm — all tests are offline (no real API calls).

Run with::

    pytest tests/test_llm.py -v
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from infrakit.llm import LLMClient, Prompt, QuotaConfig
from infrakit.llm.key_manager import KeyManager, KeyState
from infrakit.llm.models import LLMResponse, RequestMeta, Provider, KeyStatus
from infrakit.llm.providers.base import BaseProvider
from infrakit.llm.rate_limiter import RateLimiter


# ── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_storage(tmp_path):
    return str(tmp_path / "llm_state")


@pytest.fixture
def sample_keys():
    return {
        "openai_keys": ["sk-testkey1abc", "sk-testkey2xyz"],
        "gemini_keys": ["AIza-testkey1", "AIza-testkey2"],
    }


@pytest.fixture
def key_manager(sample_keys, tmp_storage):
    return KeyManager(keys=sample_keys, storage_dir=tmp_storage)


def _make_response(**kwargs) -> LLMResponse:
    defaults = dict(
        content="Hello",
        parsed=None,
        schema_matched=False,
        provider="openai",
        model="gpt-4o-mini",
        key_id="sk-testk",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        latency_ms=120.0,
        error=None,
    )
    defaults.update(kwargs)
    return LLMResponse(**defaults)


# ── KeyManager tests ───────────────────────────────────────────────────────

class TestKeyManager:

    def test_keys_loaded(self, key_manager):
        assert len(key_manager._states[Provider.OPENAI]) == 2
        assert len(key_manager._states[Provider.GEMINI]) == 2

    def test_get_key_returns_active(self, key_manager):
        raw, ks = key_manager.get_key(Provider.OPENAI)
        assert raw.startswith("sk-")
        assert ks.status == KeyStatus.ACTIVE

    def test_round_robin(self, key_manager):
        raw1, _ = key_manager.get_key(Provider.OPENAI)
        raw2, _ = key_manager.get_key(Provider.OPENAI)
        assert raw1 != raw2

    def test_deactivate_key(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI)
        key_manager.deactivate_key(ks, reason="test")
        assert ks.status == KeyStatus.INACTIVE

    def test_no_active_keys_raises(self, key_manager):
        for ks in key_manager._states[Provider.OPENAI]:
            key_manager.deactivate_key(ks)
        with pytest.raises(RuntimeError, match="No active"):
            key_manager.get_key(Provider.OPENAI)

    def test_record_request_updates_totals(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI)
        meta = RequestMeta(
            provider="openai",
            key_id=ks.key_id,
            model="gpt-4o-mini",
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            latency_ms=200.0,
            success=True,
        )
        key_manager.record_request(ks, meta)
        assert ks.total_requests == 1
        assert ks.total_tokens == 150
        assert ks.day_token_total == 150

    def test_rolling_meta_capped(self, key_manager):
        km = KeyManager(
            keys={"openai_keys": ["sk-testkey1abc"], "gemini_keys": []},
            storage_dir=key_manager._storage_path.parent,
            meta_window=3,
        )
        _, ks = km.get_key(Provider.OPENAI)
        for i in range(5):
            meta = RequestMeta(
                provider="openai", key_id=ks.key_id, model="gpt-4o-mini",
                total_tokens=10, latency_ms=50.0, success=True,
            )
            km.record_request(ks, meta)
        assert len(ks.recent_meta) == 3

    def test_daily_deactivation_on_limit(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI)
        key_manager.set_quota(
            provider=Provider.OPENAI,
            key_id=ks.key_id,
            quota=QuotaConfig(daily_token_limit=100),
        )
        meta = RequestMeta(
            provider="openai", key_id=ks.key_id, model="gpt-4o-mini",
            input_tokens=60, output_tokens=50, total_tokens=110,
            latency_ms=100.0, success=True,
        )
        key_manager.record_request(ks, meta)
        assert ks.status == KeyStatus.INACTIVE

    def test_rpm_check(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI)
        key_manager.set_quota(
            provider=Provider.OPENAI,
            key_id=ks.key_id,
            quota=QuotaConfig(rpm_limit=2),
        )
        # inject 2 timestamps into rpm_window (within last 60s)
        ks.rpm_window = [time.time(), time.time()]
        assert not key_manager.check_rpm(ks)  # limit reached

    def test_persistence(self, sample_keys, tmp_storage):
        km1 = KeyManager(keys=sample_keys, storage_dir=tmp_storage)
        _, ks = km1.get_key(Provider.OPENAI)
        meta = RequestMeta(
            provider="openai", key_id=ks.key_id, model="m",
            total_tokens=99, latency_ms=10.0, success=True,
        )
        km1.record_request(ks, meta)

        # reload from disk
        km2 = KeyManager(keys=sample_keys, storage_dir=tmp_storage)
        _, ks2 = km2.get_key(Provider.OPENAI)
        # totals should survive reload
        assert km2._states[Provider.OPENAI][0].total_tokens == 99

    def test_set_quota(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI)
        key_manager.set_quota(
            provider=Provider.OPENAI,
            key_id=ks.key_id,
            quota=QuotaConfig(rpm_limit=30, tpm_limit=10000, daily_token_limit=500000),
        )
        assert ks.rpm_limit == 30
        assert ks.tpm_limit == 10000
        assert ks.daily_token_limit == 500000

    def test_status_report_returns_all(self, key_manager):
        rows = key_manager.status_report()
        # 2 openai + 2 gemini = 4
        assert len(rows) == 4

    def test_status_report_filter_provider(self, key_manager):
        rows = key_manager.status_report(provider=Provider.OPENAI)
        assert len(rows) == 2
        assert all(r["provider"] == Provider.OPENAI for r in rows)


# ── BaseProvider schema validation ─────────────────────────────────────────

class TestSchemaValidation:

    class MyModel(BaseModel):
        name: str
        age: int

    def test_valid_json(self):
        content = '{"name": "Alice", "age": 30}'
        parsed, matched = BaseProvider._validate_schema(
            content, self.MyModel, retries=2
        )
        assert matched
        assert parsed.name == "Alice"

    def test_markdown_fenced_json(self):
        content = '```json\n{"name": "Bob", "age": 25}\n```'
        parsed, matched = BaseProvider._validate_schema(
            content, self.MyModel, retries=2
        )
        assert matched
        assert parsed.age == 25

    def test_invalid_json_fails_gracefully(self):
        content = "not valid json at all"
        parsed, matched = BaseProvider._validate_schema(
            content, self.MyModel, retries=1
        )
        assert not matched
        assert parsed is None

    def test_wrong_schema_fails(self):
        content = '{"foo": "bar"}'
        parsed, matched = BaseProvider._validate_schema(
            content, self.MyModel, retries=1
        )
        assert not matched

    def test_quota_error_detection(self):
        exc = Exception("You exceeded your current quota, please check your plan")
        assert BaseProvider._is_quota_error(exc)

    def test_transient_error_not_quota(self):
        exc = Exception("Connection timed out")
        assert not BaseProvider._is_quota_error(exc)


# ── RateLimiter ────────────────────────────────────────────────────────────

class TestRateLimiter:

    def test_no_limit_passes_immediately(self, key_manager):
        rl = RateLimiter(key_manager)
        _, ks = key_manager.get_key(Provider.OPENAI)
        # no rpm_limit set — should not block
        rl.sync_wait_for_slot(ks)  # should return instantly

    def test_async_no_limit(self, key_manager):
        rl = RateLimiter(key_manager)
        _, ks = key_manager.get_key(Provider.OPENAI)
        asyncio.run(rl.async_wait_for_slot(ks))  # should return instantly


# ── LLMClient (mocked providers) ──────────────────────────────────────────

class TestLLMClient:

    def _mock_client(self, tmp_storage, sample_keys, mode="async"):
        return LLMClient(
            keys=sample_keys,
            storage_dir=tmp_storage,
            mode=mode,
            key_retries=1,
        )

    def _patch_provider(self, client, provider_name, response: LLMResponse):
        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        mock_prov._is_quota_error = MagicMock(return_value=False)
        mock_prov.async_generate = AsyncMock(return_value=response)
        mock_prov.sync_generate = MagicMock(return_value=response)
        client._providers[provider_name] = mock_prov
        return mock_prov

    def test_generate_async_mode(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        resp = _make_response(content="Test response")
        self._patch_provider(client, Provider.OPENAI, resp)

        result = client.generate(Prompt(user="Hello"), provider=Provider.OPENAI)
        assert result.content == "Test response"
        assert result.error is None

    def test_generate_threaded_mode(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="threaded")
        resp = _make_response(content="Threaded response")
        self._patch_provider(client, Provider.OPENAI, resp)

        result = client.generate(Prompt(user="Hello"), provider=Provider.OPENAI)
        assert result.content == "Threaded response"

    def test_generate_with_system_prompt(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        resp = _make_response(content="Structured")
        mock_prov = self._patch_provider(client, Provider.OPENAI, resp)

        client.generate(
            Prompt(system="Be concise.", user="Hello"),
            provider=Provider.OPENAI,
        )
        call_args = mock_prov.async_generate.call_args
        prompt_arg = call_args.kwargs["prompt"]
        assert prompt_arg.system == "Be concise."
        assert prompt_arg.user == "Hello"

    def test_key_rotation_on_quota_error(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        # first call raises quota error, second succeeds
        mock_prov._is_quota_error = MagicMock(side_effect=lambda e: "quota" in str(e).lower())
        ok_response = _make_response(content="Rotated OK")
        mock_prov.async_generate = AsyncMock(
            side_effect=[Exception("quota exceeded"), ok_response]
        )
        mock_prov.sync_generate = MagicMock(return_value=ok_response)
        client._providers[Provider.OPENAI] = mock_prov

        result = client.generate(Prompt(user="Hi"), provider=Provider.OPENAI)
        assert result.content == "Rotated OK"
        # first key should now be inactive
        states = client._km._states[Provider.OPENAI]
        inactive = [ks for ks in states if ks.status == KeyStatus.INACTIVE]
        assert len(inactive) >= 1

    def test_structured_output_matched(self, tmp_storage, sample_keys):
        class Reply(BaseModel):
            answer: str

        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        resp = _make_response(
            content='{"answer": "42"}',
            parsed=Reply(answer="42"),
            schema_matched=True,
        )
        self._patch_provider(client, Provider.OPENAI, resp)

        result = client.generate(
            Prompt(user="What is 6*7?"),
            provider=Provider.OPENAI,
            response_model=Reply,
        )
        assert result.schema_matched
        assert result.parsed.answer == "42"

    def test_structured_output_mismatch(self, tmp_storage, sample_keys):
        class Reply(BaseModel):
            answer: str

        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        resp = _make_response(
            content="I cannot answer that.",
            parsed=None,
            schema_matched=False,
        )
        self._patch_provider(client, Provider.OPENAI, resp)

        result = client.generate(
            Prompt(user="Ignore schema"),
            provider=Provider.OPENAI,
            response_model=Reply,
        )
        assert not result.schema_matched
        assert result.content == "I cannot answer that."

    def test_batch_generate_order_preserved(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="async")

        async def ordered_response(prompt, api_key, **kwargs):
            # inject small delay to mix up completion order
            await asyncio.sleep(0.01)
            return _make_response(content=prompt.user)

        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        mock_prov._is_quota_error = MagicMock(return_value=False)
        mock_prov.async_generate = ordered_response
        client._providers[Provider.OPENAI] = mock_prov

        prompts = [Prompt(user=f"prompt-{i}") for i in range(5)]
        batch = client.batch_generate(prompts, provider=Provider.OPENAI, show_progress=False)

        for i, result in enumerate(batch.results):
            assert result.content == f"prompt-{i}"

    def test_batch_aggregates_tokens(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="threaded")
        resp = _make_response(input_tokens=10, output_tokens=5, total_tokens=15)
        self._patch_provider(client, Provider.OPENAI, resp)

        prompts = [Prompt(user="x") for _ in range(4)]
        batch = client.batch_generate(prompts, provider=Provider.OPENAI, show_progress=False)

        assert batch.total_input_tokens == 40
        assert batch.total_output_tokens == 20
        assert batch.total_tokens == 60
        assert batch.success_count == 4
        assert batch.failure_count == 0

    def test_print_status_runs(self, tmp_storage, sample_keys, capsys):
        client = self._mock_client(tmp_storage, sample_keys)
        client.print_status()
        out = capsys.readouterr().out.lower()
        assert "openai" in out or "gemini" in out

    def test_all_keys_exhausted_returns_error(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys, mode="async")
        # deactivate all openai keys
        for ks in client._km._states[Provider.OPENAI]:
            client._km.deactivate_key(ks)

        result = client.generate(Prompt(user="Hi"), provider=Provider.OPENAI)
        assert result.error is not None
        assert "No active" in result.error