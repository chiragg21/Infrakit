"""
infrakit.llm.rate_limiter
-------------------------
RPM-aware gate (key-level) and TPM-aware gate (model-level).
"""

from __future__ import annotations

import asyncio
import time

from .key_manager import KeyManager, KeyState


class RateLimiter:
    """
    Async-and-sync compatible RPM/TPM gate.

    RPM is enforced at the key level (all models share the key's request budget).
    TPM is enforced at the model level.

    Parameters
    ----------
    key_manager     Shared KeyManager instance (owns all rate state).
    poll_interval   How often (seconds) to re-check the window while waiting.
    """

    def __init__(
        self,
        key_manager: KeyManager,
        poll_interval: float = 0.25,
    ) -> None:
        self._km   = key_manager
        self._poll = poll_interval

    # ── async ──────────────────────────────────────────────────────────────

    async def async_wait_for_slot(self, ks: KeyState, model: str) -> None:
        """Async-suspend until both RPM and TPM slots are open."""
        while not self._km.check_rpm(ks):
            wait = self._km.seconds_until_rpm_slot(ks)
            await asyncio.sleep(max(wait, self._poll))
        while not self._km.check_tpm(ks, model):
            await asyncio.sleep(self._poll)

    # ── sync ───────────────────────────────────────────────────────────────

    def sync_wait_for_slot(self, ks: KeyState, model: str) -> None:
        """Blocking RPM+TPM wait. Used in sync / threaded batch mode."""
        while not self._km.check_rpm(ks):
            wait = self._km.seconds_until_rpm_slot(ks)
            time.sleep(max(wait, self._poll))
        while not self._km.check_tpm(ks, model):
            time.sleep(self._poll)