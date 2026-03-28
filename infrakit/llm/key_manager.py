"""
infrakit.llm.key_manager
------------------------
Manages API keys across providers:
- Persistent storage of key state (status, token totals, RPM window)
- Quota enforcement (RPM, TPM, daily tokens)
- Key rotation and automatic reactivation after reset
- Rolling window of recent request metadata (no prompt/response content)
"""

from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from .models import KeyStatus, Provider, QuotaConfig, RequestMeta


# ── constants ──────────────────────────────────────────────────────────────

_META_WINDOW = 50       # latest N request metadata records kept per key
_PERSIST_FILE = "llm_key_state.json"


# ── per-key runtime state ──────────────────────────────────────────────────

@dataclass
class KeyState:
    """Full runtime + persisted state for one API key."""

    # identity
    provider: str
    key_id: str                 # first 8 chars — used in logs / CLI
    key_hash: str               # sha256 of full key — used to re-match on reload

    # status
    status: str = KeyStatus.ACTIVE
    deactivated_at: Optional[float] = None   # epoch when deactivated

    # quota config (set manually by user)
    rpm_limit: Optional[int] = None
    tpm_limit: Optional[int] = None
    daily_token_limit: Optional[int] = None
    reset_hour_utc: int = 0

    # running totals (persisted)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_requests: int = 0
    total_errors: int = 0

    # daily window (reset at reset_hour_utc each day)
    day_token_total: int = 0
    day_start_epoch: float = field(default_factory=time.time)

    # RPM window — list of epoch timestamps of recent requests (persisted as list)
    rpm_window: list[float] = field(default_factory=list)

    # TPM window — list of (epoch, tokens) tuples for the last 60 s
    tpm_window: list[tuple[float, int]] = field(default_factory=list)

    # rolling metadata (latest N, no prompt/response content)
    recent_meta: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "key_id": self.key_id,
            "key_hash": self.key_hash,
            "status": self.status,
            "deactivated_at": self.deactivated_at,
            "rpm_limit": self.rpm_limit,
            "tpm_limit": self.tpm_limit,
            "daily_token_limit": self.daily_token_limit,
            "reset_hour_utc": self.reset_hour_utc,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "total_requests": self.total_requests,
            "total_errors": self.total_errors,
            "day_token_total": self.day_token_total,
            "day_start_epoch": self.day_start_epoch,
            "rpm_window": self.rpm_window,
            "tpm_window": self.tpm_window,
            "recent_meta": self.recent_meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "KeyState":
        ks = cls(
            provider=d["provider"],
            key_id=d["key_id"],
            key_hash=d["key_hash"],
        )
        ks.status = d.get("status", KeyStatus.ACTIVE)
        ks.deactivated_at = d.get("deactivated_at")
        ks.rpm_limit = d.get("rpm_limit")
        ks.tpm_limit = d.get("tpm_limit")
        ks.daily_token_limit = d.get("daily_token_limit")
        ks.reset_hour_utc = d.get("reset_hour_utc", 0)
        ks.total_input_tokens = d.get("total_input_tokens", 0)
        ks.total_output_tokens = d.get("total_output_tokens", 0)
        ks.total_tokens = d.get("total_tokens", 0)
        ks.total_requests = d.get("total_requests", 0)
        ks.total_errors = d.get("total_errors", 0)
        ks.day_token_total = d.get("day_token_total", 0)
        ks.day_start_epoch = d.get("day_start_epoch", time.time())
        ks.rpm_window = d.get("rpm_window", [])
        ks.tpm_window = [tuple(x) for x in d.get("tpm_window", [])]
        ks.recent_meta = d.get("recent_meta", [])
        return ks


# ── key manager ────────────────────────────────────────────────────────────

class KeyManager:
    """
    Thread-safe manager for all provider API keys.

    Parameters
    ----------
    keys            Dict of ``{"openai_keys": [...], "gemini_keys": [...]}``.
    storage_dir     Path to folder where key state is persisted.
    meta_window     How many recent request metadata records to keep per key.
    """

    def __init__(
        self,
        keys: dict[str, list[str]],
        storage_dir: str | Path,
        meta_window: int = _META_WINDOW,
    ) -> None:
        import hashlib

        self._lock = threading.Lock()
        self._meta_window = meta_window
        self._storage_path = Path(storage_dir) / _PERSIST_FILE
        self._storage_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing state from disk
        persisted = self._load_persisted()

        # Build key states — keyed by (provider, key_hash)
        # _states: provider -> list[KeyState]  (ordered for round-robin)
        self._states: dict[str, list[KeyState]] = {
            Provider.OPENAI: [],
            Provider.GEMINI: [],
        }
        # round-robin index per provider
        self._rr_index: dict[str, int] = {
            Provider.OPENAI: 0,
            Provider.GEMINI: 0,
        }

        provider_map = {
            "openai_keys": Provider.OPENAI,
            "gemini_keys": Provider.GEMINI,
        }

        for key_field, provider in provider_map.items():
            for raw_key in keys.get(key_field, []):
                key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
                key_id = raw_key[:8]

                # reuse persisted state if key was seen before
                existing = persisted.get((provider, key_hash))
                if existing:
                    ks = existing
                    # Re-check if it should auto-reactivate
                    self._maybe_reactivate(ks)
                else:
                    ks = KeyState(
                        provider=provider,
                        key_id=key_id,
                        key_hash=key_hash,
                    )

                # Store the raw key separately (never persisted)
                ks._raw_key = raw_key  # type: ignore[attr-defined]
                self._states[provider].append(ks)

        self._persist()

    # ── public: key acquisition ────────────────────────────────────────────

    def get_key(self, provider: str) -> tuple[str, KeyState]:
        """
        Return (raw_key, KeyState) for the next active key (round-robin).
        Raises RuntimeError if no active key is available.
        """
        with self._lock:
            self._reactivate_all_due(provider)
            candidates = self._states.get(provider, [])
            active = [ks for ks in candidates if ks.status == KeyStatus.ACTIVE]
            if not active:
                raise RuntimeError(
                    f"No active {provider} keys available. "
                    "All keys may have hit their quota."
                )
            # round-robin among active only
            idx = self._rr_index[provider] % len(active)
            ks = active[idx]
            self._rr_index[provider] = (idx + 1) % len(active)
            return ks._raw_key, ks  # type: ignore[attr-defined]

    def get_specific_key(self, provider: str, key_id: str) -> tuple[str, KeyState]:
        """Return a specific key by its key_id (first 8 chars)."""
        with self._lock:
            for ks in self._states.get(provider, []):
                if ks.key_id == key_id:
                    return ks._raw_key, ks  # type: ignore[attr-defined]
        raise KeyError(f"Key '{key_id}' not found for provider '{provider}'.")

    # ── public: RPM / TPM gate ─────────────────────────────────────────────

    def check_rpm(self, ks: KeyState) -> bool:
        """Return True if another request is allowed under RPM limit."""
        if ks.rpm_limit is None:
            return True
        now = time.time()
        # keep only timestamps in the last 60 s
        ks.rpm_window = [t for t in ks.rpm_window if now - t < 60.0]
        return len(ks.rpm_window) < ks.rpm_limit

    def check_tpm(self, ks: KeyState, tokens_needed: int = 0) -> bool:
        """Return True if another request (with approx token count) is under TPM limit."""
        if ks.tpm_limit is None:
            return True
        now = time.time()
        ks.tpm_window = [(t, tok) for t, tok in ks.tpm_window if now - t < 60.0]
        used = sum(tok for _, tok in ks.tpm_window)
        return used + tokens_needed <= ks.tpm_limit

    def seconds_until_rpm_slot(self, ks: KeyState) -> float:
        """How many seconds to wait before an RPM slot opens up."""
        if ks.rpm_limit is None or len(ks.rpm_window) < ks.rpm_limit:
            return 0.0
        oldest = min(ks.rpm_window)
        return max(0.0, 60.0 - (time.time() - oldest))

    # ── public: record a completed request ────────────────────────────────

    def record_request(self, ks: KeyState, meta: RequestMeta) -> None:
        """
        Update running totals, RPM/TPM windows, and rolling metadata.
        Call this after every API response (success or failure).
        """
        with self._lock:
            now = time.time()

            # RPM window
            ks.rpm_window.append(now)
            ks.rpm_window = [t for t in ks.rpm_window if now - t < 60.0]

            # TPM window
            ks.tpm_window.append((now, meta.total_tokens))
            ks.tpm_window = [(t, tok) for t, tok in ks.tpm_window if now - t < 60.0]

            # daily token reset
            self._maybe_reset_day(ks)
            ks.day_token_total += meta.total_tokens

            # running totals
            ks.total_requests += 1
            ks.total_input_tokens += meta.input_tokens
            ks.total_output_tokens += meta.output_tokens
            ks.total_tokens += meta.total_tokens
            if not meta.success:
                ks.total_errors += 1

            # check daily quota
            if (
                ks.daily_token_limit is not None
                and ks.day_token_total >= ks.daily_token_limit
            ):
                self._deactivate(ks, reason="daily token limit reached")

            # rolling metadata (no prompt/response)
            meta_dict = {
                "timestamp": meta.timestamp,
                "provider": meta.provider,
                "key_id": meta.key_id,
                "model": meta.model,
                "input_tokens": meta.input_tokens,
                "output_tokens": meta.output_tokens,
                "total_tokens": meta.total_tokens,
                "latency_ms": meta.latency_ms,
                "success": meta.success,
                "error": meta.error,
            }
            ks.recent_meta.append(meta_dict)
            if len(ks.recent_meta) > self._meta_window:
                ks.recent_meta = ks.recent_meta[-self._meta_window :]

            self._persist()

    def deactivate_key(self, ks: KeyState, reason: str = "quota exceeded") -> None:
        """Manually deactivate a key (e.g. on HTTP 429 / quota error)."""
        with self._lock:
            self._deactivate(ks, reason)
            self._persist()

    # ── public: quota config ───────────────────────────────────────────────

    def set_quota(
        self,
        provider: str,
        key_id: str,
        quota: QuotaConfig,
    ) -> None:
        """Set or update quota limits for a specific key."""
        with self._lock:
            for ks in self._states.get(provider, []):
                if ks.key_id == key_id:
                    ks.rpm_limit = quota.rpm_limit
                    ks.tpm_limit = quota.tpm_limit
                    ks.daily_token_limit = quota.daily_token_limit
                    ks.reset_hour_utc = quota.reset_hour_utc
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
        Return status dicts for display.  Filters by provider and/or key_id.
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
                    self._maybe_reactivate(ks)
                    self._maybe_reset_day(ks)

                    # current RPM (last 60 s)
                    current_rpm = len(
                        [t for t in ks.rpm_window if now - t < 60.0]
                    )
                    current_tpm = sum(
                        tok for t, tok in ks.tpm_window if now - t < 60.0
                    )

                    # daily tokens remaining
                    daily_remaining = None
                    if ks.daily_token_limit is not None:
                        daily_remaining = max(
                            0, ks.daily_token_limit - ks.day_token_total
                        )

                    results.append({
                        "provider": ks.provider,
                        "key_id": ks.key_id,
                        "status": ks.status,
                        "deactivated_at": ks.deactivated_at,
                        "rpm_limit": ks.rpm_limit,
                        "tpm_limit": ks.tpm_limit,
                        "daily_token_limit": ks.daily_token_limit,
                        "reset_hour_utc": ks.reset_hour_utc,
                        "current_rpm": current_rpm,
                        "current_tpm": current_tpm,
                        "day_token_total": ks.day_token_total,
                        "daily_remaining": daily_remaining,
                        "total_tokens": ks.total_tokens,
                        "total_requests": ks.total_requests,
                        "total_errors": ks.total_errors,
                        "recent_meta": ks.recent_meta[-5:],  # last 5 for CLI display
                    })
        return results

    # ── internal helpers ───────────────────────────────────────────────────

    def _deactivate(self, ks: KeyState, reason: str = "") -> None:
        ks.status = KeyStatus.INACTIVE
        ks.deactivated_at = time.time()

    def _maybe_reactivate(self, ks: KeyState) -> None:
        """Auto-reactivate if the daily reset hour has passed since deactivation."""
        if ks.status != KeyStatus.INACTIVE or ks.deactivated_at is None:
            return
        import datetime
        now_utc = datetime.datetime.now(datetime.UTC)
        reset_today = now_utc.replace(
            hour=ks.reset_hour_utc, minute=0, second=0, microsecond=0
        )
        deactivated_dt = datetime.datetime.fromtimestamp(ks.deactivated_at, datetime.UTC)
        # reactivate if reset time has passed since deactivation
        if deactivated_dt < reset_today <= now_utc:
            ks.status = KeyStatus.ACTIVE
            ks.deactivated_at = None
            ks.day_token_total = 0
            ks.day_start_epoch = time.time()

    def _reactivate_all_due(self, provider: str) -> None:
        for ks in self._states.get(provider, []):
            self._maybe_reactivate(ks)

    def _maybe_reset_day(self, ks: KeyState) -> None:
        """Reset daily token counter if the reset hour has passed today."""
        import datetime
        now_utc = datetime.datetime.now(datetime.UTC)
        reset_today = now_utc.replace(
            hour=ks.reset_hour_utc, minute=0, second=0, microsecond=0
        )
        day_start_dt = datetime.datetime.fromtimestamp(ks.day_start_epoch, datetime.UTC)
        if day_start_dt < reset_today <= now_utc:
            ks.day_token_total = 0
            ks.day_start_epoch = time.time()

    # ── persistence ────────────────────────────────────────────────────────

    def _persist(self) -> None:
        data = {}
        for provider, key_list in self._states.items():
            data[provider] = [ks.to_dict() for ks in key_list]
        try:
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2)
        except OSError:
            pass  # non-fatal — state lives in memory

    def _load_persisted(self) -> dict[tuple[str, str], KeyState]:
        if not self._storage_path.exists():
            return {}
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

        result: dict[tuple[str, str], KeyState] = {}
        for provider, key_list in data.items():
            for d in key_list:
                ks = KeyState.from_dict(d)
                result[(provider, ks.key_hash)] = ks
        return result