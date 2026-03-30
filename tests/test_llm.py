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
        "openai_keys": ["sk-key1-aaaaaa", "sk-key2-bbbbbb"],
        "gemini_keys": ["AIza-key1-aaaa", "AIza-key2-bbbb"],
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
        raw, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        assert raw.startswith("sk-")
        assert ks.status == KeyStatus.ACTIVE

    def test_round_robin(self, key_manager):
        raw1, _ = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        raw2, _ = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        assert raw1 != raw2

    def test_deactivate_key(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        key_manager.deactivate_key(ks, reason="test")
        assert ks.status == KeyStatus.INACTIVE

    def test_no_active_keys_raises(self, key_manager):
        # deactivate the specific model on all keys so get_key raises
        for ks in key_manager._states[Provider.OPENAI]:
            key_manager.deactivate_model(ks, "gpt-4o-mini")
        with pytest.raises(RuntimeError, match="No active"):
            key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")

    def test_record_request_updates_totals(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
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
        # totals are tracked on the model state, not the key state
        ms = ks.model_states["gpt-4o-mini"]
        assert ms.total_requests == 1
        assert ms.total_tokens == 150
        assert ms.day_token_total == 150

    def test_rolling_meta_capped(self, key_manager):
        km = KeyManager(
            keys={"openai_keys": ["sk-testkey1abc"], "gemini_keys": []},
            storage_dir=key_manager._storage_path.parent,
            meta_window=3,
        )
        _, ks = km.get_key(Provider.OPENAI, "gpt-4o-mini")
        for i in range(5):
            meta = RequestMeta(
                provider="openai", key_id=ks.key_id, model="gpt-4o-mini",
                total_tokens=10, latency_ms=50.0, success=True,
            )
            km.record_request(ks, meta)
        assert len(ks.recent_meta) == 3

    def test_daily_deactivation_on_limit(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        # use a model-specific quota so it applies to the model state directly
        key_manager.set_quota(
            provider=Provider.OPENAI,
            key_id=ks.key_id,
            quota=QuotaConfig(model="gpt-4o-mini", daily_token_limit=100),
        )
        meta = RequestMeta(
            provider="openai", key_id=ks.key_id, model="gpt-4o-mini",
            input_tokens=60, output_tokens=50, total_tokens=110,
            latency_ms=100.0, success=True,
        )
        key_manager.record_request(ks, meta)
        assert ks.status == KeyStatus.INACTIVE

    def test_rpm_check(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
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
        _, ks = km1.get_key(Provider.OPENAI, "gpt-4o-mini")
        meta = RequestMeta(
            provider="openai", key_id=ks.key_id, model="gpt-4o-mini",
            total_tokens=99, latency_ms=10.0, success=True,
        )
        km1.record_request(ks, meta)

        # reload from disk
        km2 = KeyManager(keys=sample_keys, storage_dir=tmp_storage)
        # totals on the model state survive reload
        assert km2._states[Provider.OPENAI][0].model_states["gpt-4o-mini"].total_tokens == 99

    def test_set_quota(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        key_manager.set_quota(
            provider=Provider.OPENAI,
            key_id=ks.key_id,
            quota=QuotaConfig(
                model="gpt-4o-mini",
                rpm_limit=30,
                tpm_limit=10000,
                daily_token_limit=500000,
            ),
        )
        # RPM limit lives on the key; TPM/daily live on the model state
        assert ks.rpm_limit == 30
        ms = ks.model_states["gpt-4o-mini"]
        assert ms.tpm_limit == 10000
        assert ms.daily_token_limit == 500000

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
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        # no rpm_limit set — should not block
        rl.sync_wait_for_slot(ks, "gpt-4o-mini")  # should return instantly

    def test_async_no_limit(self, key_manager):
        rl = RateLimiter(key_manager)
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        asyncio.run(rl.async_wait_for_slot(ks, "gpt-4o-mini"))  # should return instantly


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
        # generate() → _sync_single_generate() → sync_generate()
        call_args = mock_prov.sync_generate.call_args
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
        mock_prov.async_generate = AsyncMock(return_value=ok_response)
        # generate() → _sync_single_generate() → sync_generate()
        mock_prov.sync_generate = MagicMock(
            side_effect=[Exception("quota exceeded"), ok_response]
        )
        client._providers[Provider.OPENAI] = mock_prov

        result = client.generate(Prompt(user="Hi"), provider=Provider.OPENAI)
        assert result.content == "Rotated OK"
        # the key that received the quota error should have its model deactivated
        states = client._km._states[Provider.OPENAI]
        model_deactivated = [
            ks for ks in states
            if not ks.is_model_active(mock_prov.model)
        ]
        assert len(model_deactivated) >= 1

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


# ── Additional coverage ────────────────────────────────────────────────────


class TestClientStatus:
    """client.status() and client.set_quota() at the LLMClient level."""

    def _make_client(self, tmp_storage, sample_keys):
        return LLMClient(keys=sample_keys, storage_dir=tmp_storage)

    def test_status_returns_all_keys(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        rows = client.status()
        assert len(rows) == 4   # 2 openai + 2 gemini

    def test_status_filter_provider(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        rows = client.status(provider=Provider.OPENAI)
        assert len(rows) == 2
        assert all(r["provider"] == Provider.OPENAI for r in rows)

    def test_status_filter_key_id(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        all_rows = client.status(provider=Provider.OPENAI)
        first_key_id = all_rows[0]["key_id"]
        rows = client.status(provider=Provider.OPENAI, key_id=first_key_id)
        assert len(rows) == 1
        assert rows[0]["key_id"] == first_key_id

    def test_status_row_has_expected_fields(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        row = client.status()[0]
        for field in ("provider", "key_id", "status", "rpm_limit", "current_rpm", "models"):
            assert field in row, f"missing field {field!r} in status row"

    def test_set_quota_via_client(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        row = client.status(provider=Provider.OPENAI)[0]
        key_id = row["key_id"]

        client.set_quota(
            provider=Provider.OPENAI,
            key_id=key_id,
            quota=QuotaConfig(rpm_limit=10),
        )
        ks = client._km._states[Provider.OPENAI][0]
        assert ks.rpm_limit == 10

    def test_set_quota_model_scope(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        row = client.status(provider=Provider.OPENAI)[0]
        key_id = row["key_id"]

        client.set_quota(
            provider=Provider.OPENAI,
            key_id=key_id,
            quota=QuotaConfig(model="gpt-4o-mini", daily_token_limit=50_000),
        )
        ks = client._km._states[Provider.OPENAI][0]
        ms = ks.model_states.get("gpt-4o-mini")
        assert ms is not None
        assert ms.daily_token_limit == 50_000

    def test_unknown_provider_raises(self, tmp_storage, sample_keys):
        client = self._make_client(tmp_storage, sample_keys)
        with pytest.raises(ValueError, match="Unknown provider"):
            client.generate(Prompt(user="x"), provider="anthropic")


class TestAsyncGenerate:
    """async_generate() and async_batch_generate() public methods."""

    def _mock_client(self, tmp_storage, sample_keys):
        return LLMClient(keys=sample_keys, storage_dir=tmp_storage)

    def _patch_provider(self, client, provider_name, response):
        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        mock_prov._is_quota_error = MagicMock(return_value=False)
        mock_prov.async_generate = AsyncMock(return_value=response)
        mock_prov.sync_generate = MagicMock(return_value=response)
        client._providers[provider_name] = mock_prov
        return mock_prov

    def test_async_generate_returns_response(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys)
        resp = _make_response(content="async result")
        self._patch_provider(client, Provider.OPENAI, resp)

        result = asyncio.run(
            client.async_generate(Prompt(user="Hello"), provider=Provider.OPENAI)
        )
        assert result.content == "async result"
        assert result.error is None

    def test_async_batch_generate_order_preserved(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys)

        async def ordered(prompt, api_key, **kw):
            await asyncio.sleep(0.01)
            return _make_response(content=prompt.user)

        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        mock_prov._is_quota_error = MagicMock(return_value=False)
        mock_prov.async_generate = ordered
        client._providers[Provider.OPENAI] = mock_prov

        prompts = [Prompt(user=f"item-{i}") for i in range(4)]
        batch = asyncio.run(
            client.async_batch_generate(prompts, provider=Provider.OPENAI, show_progress=False)
        )

        assert batch.success_count == 4
        for i, r in enumerate(batch.results):
            assert r.content == f"item-{i}"

    def test_batch_max_concurrent_override(self, tmp_storage, sample_keys):
        client = self._mock_client(tmp_storage, sample_keys)
        resp = _make_response(content="ok")
        self._patch_provider(client, Provider.OPENAI, resp)

        prompts = [Prompt(user="x") for _ in range(3)]
        batch = client.batch_generate(
            prompts, provider=Provider.OPENAI,
            max_concurrent=1, show_progress=False,
        )
        assert batch.success_count == 3

    def test_batch_result_has_latency(self, tmp_storage, sample_keys):
        client = LLMClient(keys=sample_keys, storage_dir=tmp_storage, mode="threaded")
        resp = _make_response(latency_ms=50.0)
        mock_prov = MagicMock()
        mock_prov.model = "test-model"
        mock_prov._is_quota_error = MagicMock(return_value=False)
        mock_prov.sync_generate = MagicMock(return_value=resp)
        client._providers[Provider.OPENAI] = mock_prov

        batch = client.batch_generate(
            [Prompt(user="x"), Prompt(user="y")],
            provider=Provider.OPENAI, show_progress=False,
        )
        assert batch.total_latency_ms >= 0


class TestModelLevelDeactivation:
    """deactivate_model(): key remains usable for other models."""

    def test_model_deactivated_key_still_active_for_others(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        key_manager.deactivate_model(ks, "gpt-4o-mini")
        # key is inactive for gpt-4o-mini
        assert not ks.is_model_active("gpt-4o-mini")
        # but still active for a different model
        assert ks.is_model_active("gpt-4o")

    def test_key_fully_inactive_only_when_all_models_down(self, key_manager):
        _, ks = key_manager.get_key(Provider.OPENAI, "gpt-4o-mini")
        key_manager.deactivate_model(ks, "gpt-4o-mini")
        # single model deactivated → key is INACTIVE (no other models known)
        assert ks.status == KeyStatus.INACTIVE

        # add an active model state manually
        ks.model_states["gpt-4o"] = ks.model_states["gpt-4o-mini"].__class__(model="gpt-4o")
        # now key has one active model → key is ACTIVE again
        assert ks.status == KeyStatus.ACTIVE


class TestQuotaFileLoading:
    """KeyManager loads quotas from a JSON file."""

    def test_quota_file_sets_rpm(self, tmp_path, sample_keys):
        quota_file = tmp_path / "quotas.json"
        quota_file.write_text('{"openai": {"default": {"rpm": 20}}}')

        km = KeyManager(
            keys=sample_keys,
            storage_dir=tmp_path / "state",
            quota_file=str(quota_file),
        )
        # rpm_limit should be applied to all openai keys
        for ks in km._states[Provider.OPENAI]:
            assert ks.rpm_limit == 20

    def test_quota_file_sets_model_daily_limit(self, tmp_path, sample_keys):
        quota_file = tmp_path / "quotas.json"
        quota_file.write_text(
            '{"openai": {"gpt-4o-mini": {"daily_tokens": 100000}}}'
        )
        km = KeyManager(
            keys=sample_keys,
            storage_dir=tmp_path / "state",
            quota_file=str(quota_file),
        )
        for ks in km._states[Provider.OPENAI]:
            ms = ks.model_states.get("gpt-4o-mini")
            assert ms is not None
            assert ms.daily_token_limit == 100_000

    def test_bad_quota_file_silently_ignored(self, tmp_path, sample_keys):
        quota_file = tmp_path / "quotas.json"
        quota_file.write_text("not valid json {{{")

        # should not raise — just prints a warning
        km = KeyManager(
            keys=sample_keys,
            storage_dir=tmp_path / "state",
            quota_file=str(quota_file),
        )
        assert len(km._states[Provider.OPENAI]) == 2