"""
infrakit.llm.key_manager
------------------------
Manages API keys across providers with model-level quota tracking.

Key design
----------
- Deactivation is at the (key, model) level, not the key level.
  A key is only fully deactivated when ALL its models are inactive.
  Exhausting gemini-2.5-pro leaves gemini-2.5-flash available on the
  same key.

- RPM is tracked at the key level (the API counts all calls regardless
  of model).  TPM and daily tokens are tracked per model.

- Quota can be loaded from a JSON file so users don't have to call
  set_quota() in code every session.

- Default storage paths live under ~/.infrakit/llm/ so state persists
  across projects using the same keys.
"""

from __future__ import annotations

import datetime
import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .models import KeyStatus, ModelStatus, Provider, QuotaConfig, RequestMeta


# ── default paths ──────────────────────────────────────────────────────────

#: Default directory for all infrakit LLM state files.
DEFAULT_LLM_DIR: Path = Path.home() / ".infrakit" / "llm"

#: Default path for the key state persistence file.
DEFAULT_STATE_FILE: Path = DEFAULT_LLM_DIR / "key_state.json"

#: Default path for the quota definition file.
DEFAULT_QUOTA_FILE: Path = DEFAULT_LLM_DIR / "quotas.json"

# internal constants
_META_WINDOW  = 50    # rolling metadata records per key
_STATE_FILE   = "key_state.json"
_QUOTA_FILE   = "quotas.json"


# ── model-level state ──────────────────────────────────────────────────────

@dataclass
class ModelState:
    """
    Per-model quota state for one API key.

    Tracks usage and status independently so exhausting one model does
    not block others on the same key.
    """
    model: str
    status: str = ModelStatus.ACTIVE
    deactivated_at: Optional[float] = None

    # quota config for this model (merged from file + set_quota calls)
    tpm_limit: Optional[int] = None
    daily_token_limit: Optional[int] = None
    reset_hour_utc: int = 0

    # daily usage window
    day_token_total: int = 0
    day_start_epoch: float = field(default_factory=time.time)

    # TPM sliding window — list of (epoch, tokens)
    tpm_window: list[tuple[float, int]] = field(default_factory=list)

    # per-model lifetime totals
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_requests: int = 0
    total_errors: int = 0

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "status": self.status,
            "deactivated_at": self.deactivated_at,
            "tpm_limit": self.tpm_limit,
            "daily_token_limit": self.daily_token_limit,
            "reset_hour_utc": self.reset_hour_utc,
            "day_token_total": self.day_token_total,
            "day_start_epoch": self.day_start_epoch,
            "tpm_window": self.tpm_window,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelState":
        ms = cls(model=d["model"])
        ms.status          = d.get("status", ModelStatus.ACTIVE)
        ms.deactivated_at  = d.get("deactivated_at")
        ms.tpm_limit       = d.get("tpm_limit")
        ms.daily_token_limit = d.get("daily_token_limit")
        ms.reset_hour_utc  = d.get("reset_hour_utc", 0)
        ms.day_token_total = d.get("day_token_total", 0)
        ms.day_start_epoch = d.get("day_start_epoch", time.time())
        ms.tpm_window      = [tuple(x) for x in d.get("tpm_window", [])]
        ms.total_input_tokens  = d.get("total_input_tokens", 0)
        ms.total_output_tokens = d.get("total_output_tokens", 0)
        ms.total_tokens    = d.get("total_tokens", 0)
        ms.total_requests  = d.get("total_requests", 0)
        ms.total_errors    = d.get("total_errors", 0)
        return ms


# ── per-key state ──────────────────────────────────────────────────────────

@dataclass
class KeyState:
    """
    Full runtime + persisted state for one API key.

    Key-level fields
    ----------------
    rpm_limit / rpm_window  RPM is shared across all models on this key.
    model_states            Per-model quota and usage state.
    recent_meta             Rolling metadata window (no prompt/response content).

    The key's overall ``status`` is derived: ACTIVE if at least one model
    is active, INACTIVE if all models are inactive.
    """

    # identity
    provider: str
    key_id: str     # first 8 chars of raw key — safe for logs
    key_hash: str   # sha256 — used to re-match on reload (raw key never stored)

    # key-level RPM (shared across models)
    rpm_limit: Optional[int] = None
    rpm_window: list[float] = field(default_factory=list)

    # per-model state — keyed by model string
    model_states: dict[str, ModelState] = field(default_factory=dict)

    # rolling metadata (no prompt/response)
    recent_meta: list[dict] = field(default_factory=list)

    # ── derived status ────────────────────────────────────────────────────

    @property
    def status(self) -> str:
        """ACTIVE if any model state is active, INACTIVE if all are inactive."""
        if not self.model_states:
            return KeyStatus.ACTIVE   # no model tracking yet — assume active
        if any(ms.status == ModelStatus.ACTIVE for ms in self.model_states.values()):
            return KeyStatus.ACTIVE
        return KeyStatus.INACTIVE

    def is_model_active(self, model: str) -> bool:
        ms = self.model_states.get(model)
        return ms is None or ms.status == ModelStatus.ACTIVE

    def get_or_create_model_state(self, model: str) -> ModelState:
        if model not in self.model_states:
            self.model_states[model] = ModelState(model=model)
        return self.model_states[model]

    # ── serialisation ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "key_id": self.key_id,
            "key_hash": self.key_hash,
            "rpm_limit": self.rpm_limit,
            "rpm_window": self.rpm_window,
            "model_states": {
                m: ms.to_dict() for m, ms in self.model_states.items()
            },
            "recent_meta": self.recent_meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KeyState":
        ks = cls(
            provider=d["provider"],
            key_id=d["key_id"],
            key_hash=d["key_hash"],
        )
        ks.rpm_limit  = d.get("rpm_limit")
        ks.rpm_window = d.get("rpm_window", [])
        ks.recent_meta = d.get("recent_meta", [])
        for model_str, ms_dict in d.get("model_states", {}).items():
            ks.model_states[model_str] = ModelState.from_dict(ms_dict)
        return ks


# ── key manager ────────────────────────────────────────────────────────────

class KeyManager:
    """
    Thread-safe manager for all provider API keys.

    Parameters
    ----------
    keys            ``{"openai_keys": [...], "gemini_keys": [...]}``.
    storage_dir     Folder where ``key_state.json`` is written.
                    Defaults to ``~/.infrakit/llm/``.
    quota_file      Path to a JSON quota definition file.
                    Defaults to ``~/.infrakit/llm/quotas.json``.
                    Pass ``None`` to skip file-based quota loading.
    meta_window     Rolling metadata records kept per key.
    """

    def __init__(
        self,
        keys: dict[str, list[str]],
        storage_dir: Optional[str | Path] = None,
        quota_file: Optional[str | Path] = None,
        meta_window: int = _META_WINDOW,
    ) -> None:
        import hashlib

        self._lock = threading.Lock()
        self._meta_window = meta_window

        # ── resolve paths ─────────────────────────────────────────────────
        storage_path = Path(storage_dir) if storage_dir else DEFAULT_LLM_DIR
        storage_path.mkdir(parents=True, exist_ok=True)
        self._storage_path = storage_path / _STATE_FILE

        # quota file: explicit arg > default location > skip
        if quota_file is not None:
            self._quota_file: Optional[Path] = Path(quota_file)
        elif (DEFAULT_LLM_DIR / _QUOTA_FILE).exists():
            self._quota_file = DEFAULT_LLM_DIR / _QUOTA_FILE
        else:
            self._quota_file = None

        # ── load persisted state & quota file ─────────────────────────────
        persisted    = self._load_persisted()
        file_quotas  = self._load_quota_file()   # {provider: {model|"default": QuotaConfig}}

        # ── build in-memory structures ────────────────────────────────────
        self._states: dict[str, list[KeyState]] = {
            Provider.OPENAI: [],
            Provider.GEMINI: [],
        }
        self._rr_index: dict[str, dict[str, int]] = {
            # per-provider, per-model round-robin index
            Provider.OPENAI: {},
            Provider.GEMINI: {},
        }

        provider_map = {
            "openai_keys": Provider.OPENAI,
            "gemini_keys": Provider.GEMINI,
        }

        for key_field, provider in provider_map.items():
            for raw_key in keys.get(key_field, []):
                key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                key_id   = raw_key[:8]

                existing = persisted.get((provider, key_hash))
                if existing:
                    ks = existing
                    # auto-reactivate any models whose reset time has passed
                    for ms in ks.model_states.values():
                        self._maybe_reactivate_model(ms)
                else:
                    ks = KeyState(provider=provider, key_id=key_id, key_hash=key_hash)

                # Apply file-level quota defaults for this provider
                # (only sets fields not already configured on persisted state)
                self._apply_file_quotas(ks, file_quotas.get(provider, {}))

                ks._raw_key = raw_key  # type: ignore[attr-defined]
                self._states[provider].append(ks)

        self._persist()

    # ── public: key acquisition ────────────────────────────────────────────

    def get_key(self, provider: str, model: str) -> tuple[str, KeyState]:
        """
        Return (raw_key, KeyState) for the next key that has *model* active.

        Round-robins separately per (provider, model) so different models
        can be load-balanced independently.

        Raises RuntimeError if no key has this model available.
        """
        with self._lock:
            self._reactivate_all_due(provider)
            candidates = self._states.get(provider, [])

            # keys where this specific model is not deactivated
            eligible = [ks for ks in candidates if ks.is_model_active(model)]
            if not eligible:
                raise RuntimeError(
                    f"No active {provider} keys available for model '{model}'. "
                    "All keys may have hit their quota for this model."
                )

            rr = self._rr_index[provider]
            idx = rr.get(model, 0) % len(eligible)
            ks  = eligible[idx]
            rr[model] = (idx + 1) % len(eligible)

            return ks._raw_key, ks  # type: ignore[attr-defined]

    # ── public: rate-limit checks ──────────────────────────────────────────

    def check_rpm(self, ks: KeyState) -> bool:
        """True if another request is allowed under the key-level RPM limit."""
        if ks.rpm_limit is None:
            return True
        now = time.time()
        ks.rpm_window = [t for t in ks.rpm_window if now - t < 60.0]
        return len(ks.rpm_window) < ks.rpm_limit

    def check_tpm(self, ks: KeyState, model: str, tokens_needed: int = 0) -> bool:
        """True if another request is allowed under the model-level TPM limit."""
        ms = ks.model_states.get(model)
        if ms is None or ms.tpm_limit is None:
            return True
        now = time.time()
        ms.tpm_window = [(t, tok) for t, tok in ms.tpm_window if now - t < 60.0]
        used = sum(tok for _, tok in ms.tpm_window)
        return used + tokens_needed <= ms.tpm_limit

    def seconds_until_rpm_slot(self, ks: KeyState) -> float:
        if ks.rpm_limit is None or len(ks.rpm_window) < ks.rpm_limit:
            return 0.0
        oldest = min(ks.rpm_window)
        return max(0.0, 60.0 - (time.time() - oldest))

    # ── public: record a completed request ────────────────────────────────

    def record_request(self, ks: KeyState, meta: RequestMeta) -> None:
        """
        Update all counters after an API call (success or failure).
        - RPM window updated at key level.
        - TPM window, daily tokens, totals updated at model level.
        - Rolling metadata appended (no prompt/response content).
        """
        with self._lock:
            now   = time.time()
            model = meta.model

            # ── key-level RPM ─────────────────────────────────────────────
            ks.rpm_window.append(now)
            ks.rpm_window = [t for t in ks.rpm_window if now - t < 60.0]

            # ── model-level state ─────────────────────────────────────────
            ms = ks.get_or_create_model_state(model)

            ms.tpm_window.append((now, meta.total_tokens))
            ms.tpm_window = [(t, tok) for t, tok in ms.tpm_window if now - t < 60.0]

            self._maybe_reset_day(ms)
            ms.day_token_total += meta.total_tokens

            ms.total_requests      += 1
            ms.total_input_tokens  += meta.input_tokens
            ms.total_output_tokens += meta.output_tokens
            ms.total_tokens        += meta.total_tokens
            if not meta.success:
                ms.total_errors += 1

            # check model-level daily quota
            if (
                ms.daily_token_limit is not None
                and ms.day_token_total >= ms.daily_token_limit
            ):
                self._deactivate_model(ms, reason="daily token limit reached")

            # ── rolling metadata ──────────────────────────────────────────
            ks.recent_meta.append({
                "timestamp":     meta.timestamp,
                "provider":      meta.provider,
                "key_id":        meta.key_id,
                "model":         model,
                "input_tokens":  meta.input_tokens,
                "output_tokens": meta.output_tokens,
                "total_tokens":  meta.total_tokens,
                "latency_ms":    meta.latency_ms,
                "success":       meta.success,
                "error":         meta.error,
            })
            if len(ks.recent_meta) > self._meta_window:
                ks.recent_meta = ks.recent_meta[-self._meta_window:]

            self._persist()

    def deactivate_model(
        self, ks: KeyState, model: str, reason: str = "quota exceeded"
    ) -> None:
        """
        Mark a specific (key, model) pair as inactive.

        The key itself remains available for other models.  The key is
        only considered fully inactive when every tracked model is inactive.
        """
        with self._lock:
            ms = ks.get_or_create_model_state(model)
            self._deactivate_model(ms, reason=reason)
            self._persist()

    # kept for backwards-compat — deactivates ALL models on the key
    def deactivate_key(self, ks: KeyState, reason: str = "quota exceeded") -> None:
        """Deactivate all models on a key (hard failure like bad API key)."""
        with self._lock:
            for ms in ks.model_states.values():
                self._deactivate_model(ms, reason=reason)
            # if no model states exist yet, add a sentinel
            if not ks.model_states:
                sentinel = ModelState(model="__all__")
                self._deactivate_model(sentinel, reason=reason)
                ks.model_states["__all__"] = sentinel
            self._persist()

    # ── public: quota config ───────────────────────────────────────────────

    def set_quota(
        self,
        provider: str,
        key_id: str,
        quota: QuotaConfig,
    ) -> None:
        """
        Set quota for a key, optionally for a specific model.

        If ``quota.model`` is None the config is treated as the default
        for all models on this key that don't have their own entry.
        If ``quota.model`` is set, it applies only to that model.
        """
        with self._lock:
            for ks in self._states.get(provider, []):
                if ks.key_id != key_id:
                    continue

                # key-level RPM (always updated regardless of model scope)
                if quota.rpm_limit is not None:
                    ks.rpm_limit = quota.rpm_limit

                target_model = quota.model  # None = default

                if target_model is None:
                    # apply as default to all existing model states
                    # and store as a special "__default__" entry for new models
                    self._apply_quota_to_model_state(
                        ks.get_or_create_model_state("__default__"), quota
                    )
                    # also propagate to already-known models that have no override
                    for ms in ks.model_states.values():
                        if ms.model == "__default__":
                            continue
                        if not self._has_explicit_quota(ms):
                            self._apply_quota_to_model_state(ms, quota)
                else:
                    ms = ks.get_or_create_model_state(target_model)
                    self._apply_quota_to_model_state(ms, quota)

                self._persist()
                return

        raise KeyError(f"Key '{key_id}' not found for provider '{provider}'.")

    # ── public: status report ──────────────────────────────────────────────

    def status_report(
        self,
        provider: Optional[str] = None,
        key_id: Optional[str] = None,
    ) -> list[dict]:
        """
        Return status dicts for CLI / programmatic display.
        Filters by provider and/or key_id.
        """
        now = time.time()
        results = []

        with self._lock:
            for prov, key_list in self._states.items():
                if provider and prov != provider:
                    continue

                for ks in key_list:
                    if key_id and ks.key_id != key_id:
                        continue

                    # refresh reactivation state before reporting
                    for ms in ks.model_states.values():
                        self._maybe_reactivate_model(ms)

                    current_rpm = len([t for t in ks.rpm_window if now - t < 60.0])

                    model_rows = []
                    for model_name, ms in ks.model_states.items():
                        if model_name == "__default__":
                            continue
                        self._maybe_reset_day(ms)
                        current_tpm = sum(
                            tok for t, tok in ms.tpm_window if now - t < 60.0
                        )
                        daily_remaining = (
                            max(0, ms.daily_token_limit - ms.day_token_total)
                            if ms.daily_token_limit is not None else None
                        )
                        model_rows.append({
                            "model":           model_name,
                            "status":          ms.status,
                            "deactivated_at":  ms.deactivated_at,
                            "tpm_limit":       ms.tpm_limit,
                            "daily_token_limit": ms.daily_token_limit,
                            "reset_hour_utc":  ms.reset_hour_utc,
                            "current_tpm":     current_tpm,
                            "day_token_total": ms.day_token_total,
                            "daily_remaining": daily_remaining,
                            "total_tokens":    ms.total_tokens,
                            "total_requests":  ms.total_requests,
                            "total_errors":    ms.total_errors,
                        })

                    results.append({
                        "provider":     ks.provider,
                        "key_id":       ks.key_id,
                        "status":       ks.status,
                        "rpm_limit":    ks.rpm_limit,
                        "current_rpm":  current_rpm,
                        "models":       model_rows,
                        "recent_meta":  ks.recent_meta[-5:],
                    })

        return results

    # ── internal: deactivation & reactivation ─────────────────────────────

    def _deactivate_model(self, ms: ModelState, reason: str = "") -> None:
        ms.status         = ModelStatus.INACTIVE
        ms.deactivated_at = time.time()

    def _maybe_reactivate_model(self, ms: ModelState) -> None:
        """Auto-reactivate a model if its daily reset hour has passed."""
        if ms.status != ModelStatus.INACTIVE or ms.deactivated_at is None:
            return
        now_utc = datetime.datetime.utcnow()
        reset_today = now_utc.replace(
            hour=ms.reset_hour_utc, minute=0, second=0, microsecond=0
        )
        deactivated_dt = datetime.datetime.utcfromtimestamp(ms.deactivated_at)
        if deactivated_dt < reset_today <= now_utc:
            ms.status         = ModelStatus.ACTIVE
            ms.deactivated_at = None
            ms.day_token_total = 0
            ms.day_start_epoch = time.time()

    def _reactivate_all_due(self, provider: str) -> None:
        for ks in self._states.get(provider, []):
            for ms in ks.model_states.values():
                self._maybe_reactivate_model(ms)

    def _maybe_reset_day(self, ms: ModelState) -> None:
        """Reset daily token counter if the reset hour has passed today."""
        now_utc = datetime.datetime.utcnow()
        reset_today = now_utc.replace(
            hour=ms.reset_hour_utc, minute=0, second=0, microsecond=0
        )
        day_start_dt = datetime.datetime.utcfromtimestamp(ms.day_start_epoch)
        if day_start_dt < reset_today <= now_utc:
            ms.day_token_total = 0
            ms.day_start_epoch = time.time()

    # ── internal: quota helpers ────────────────────────────────────────────

    @staticmethod
    def _apply_quota_to_model_state(ms: ModelState, quota: QuotaConfig) -> None:
        if quota.tpm_limit is not None:
            ms.tpm_limit = quota.tpm_limit
        if quota.daily_token_limit is not None:
            ms.daily_token_limit = quota.daily_token_limit
        if quota.reset_hour_utc is not None:
            ms.reset_hour_utc = quota.reset_hour_utc

    @staticmethod
    def _has_explicit_quota(ms: ModelState) -> bool:
        """True if any quota field was explicitly set on this ModelState."""
        return any([
            ms.tpm_limit is not None,
            ms.daily_token_limit is not None,
        ])

    def _apply_file_quotas(
        self,
        ks: KeyState,
        provider_quotas: dict[str, QuotaConfig],
    ) -> None:
        """
        Apply quotas loaded from the quota file onto a KeyState.

        ``provider_quotas`` is keyed by model name or ``"default"``.
        Only sets fields that aren't already configured (persisted state wins).
        """
        default_q = provider_quotas.get("default")

        # key-level RPM from default or explicit key config
        if ks.rpm_limit is None and default_q and default_q.rpm_limit:
            ks.rpm_limit = default_q.rpm_limit

        for model_name, quota in provider_quotas.items():
            if model_name == "default":
                # store as __default__ so new model states inherit it
                dflt_ms = ks.get_or_create_model_state("__default__")
                if not self._has_explicit_quota(dflt_ms):
                    self._apply_quota_to_model_state(dflt_ms, quota)
            else:
                ms = ks.get_or_create_model_state(model_name)
                if not self._has_explicit_quota(ms):
                    self._apply_quota_to_model_state(ms, quota)
                # model-specific rpm_limit overrides key-level if set
                if quota.rpm_limit is not None and ks.rpm_limit is None:
                    ks.rpm_limit = quota.rpm_limit

    def _get_effective_model_quota(self, ks: KeyState, model: str) -> ModelState:
        """
        Return the ModelState for *model*, inheriting from __default__ if
        the model has no explicit quota set.
        """
        ms = ks.get_or_create_model_state(model)
        default_ms = ks.model_states.get("__default__")
        if default_ms and not self._has_explicit_quota(ms):
            if ms.tpm_limit is None and default_ms.tpm_limit is not None:
                ms.tpm_limit = default_ms.tpm_limit
            if ms.daily_token_limit is None and default_ms.daily_token_limit is not None:
                ms.daily_token_limit = default_ms.daily_token_limit
            if ms.reset_hour_utc == 0 and default_ms.reset_hour_utc != 0:
                ms.reset_hour_utc = default_ms.reset_hour_utc
        return ms

    # ── internal: quota file loading ───────────────────────────────────────

    def _load_quota_file(self) -> dict[str, dict[str, QuotaConfig]]:
        """
        Load quotas.json and return a nested dict:
            { provider: { model_or_"default": QuotaConfig } }

        File format::

            {
              "openai": {
                "default":    { "rpm": 60, "tpm": 90000, "daily_tokens": 1000000, "reset_hour_utc": 0 },
                "gpt-4o":     { "rpm": 10, "daily_tokens": 100000 }
              },
              "gemini": {
                "default":              { "rpm": 15 },
                "gemini-2.0-flash":     { "daily_tokens": 1500000 },
                "gemini-2.5-pro":       { "daily_tokens": 250000 }
              }
            }

        All fields are optional.  Unknown fields are ignored.
        """
        if self._quota_file is None or not self._quota_file.exists():
            return {}

        try:
            with open(self._quota_file, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[infrakit.llm] Warning: could not load quota file "
                  f"'{self._quota_file}': {exc}")
            return {}

        result: dict[str, dict[str, QuotaConfig]] = {}
        for provider, models in raw.items():
            if not isinstance(models, dict):
                continue
            result[provider] = {}
            for model_key, cfg in models.items():
                if not isinstance(cfg, dict):
                    continue
                result[provider][model_key] = QuotaConfig(
                    model=None if model_key == "default" else model_key,
                    rpm_limit=cfg.get("rpm"),
                    tpm_limit=cfg.get("tpm"),
                    daily_token_limit=cfg.get("daily_tokens"),
                    reset_hour_utc=cfg.get("reset_hour_utc", 0),
                )

        return result

    # ── internal: persistence ──────────────────────────────────────────────

    def _persist(self) -> None:
        data = {
            prov: [ks.to_dict() for ks in key_list]
            for prov, key_list in self._states.items()
        }
        try:
            with open(self._storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass  # non-fatal

    def _load_persisted(self) -> dict[tuple[str, str], KeyState]:
        if not self._storage_path.exists():
            return {}
        try:
            with open(self._storage_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

        result: dict[tuple[str, str], KeyState] = {}
        for provider, key_list in data.items():
            for d in key_list:
                ks = KeyState.from_dict(d)
                result[(provider, ks.key_hash)] = ks
        return result