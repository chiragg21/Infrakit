"""
infrakit.llm.rate_limiter
-------------------------
RPM-aware gate that sits in front of every API call.

The rate limiter inspects the KeyState's rpm_window and, if the limit
is already reached, sleeps until a slot opens.  It is intentionally
kept thin — all state lives in KeyManager / KeyState so it persists
across sessions.
"""

from __future__ import annotations

import asyncio
import time

from .key_manager import KeyManager, KeyState


class RateLimiter:
    """
    Async-and-sync compatible RPM gate.

    Parameters
    ----------
    key_manager     Shared KeyManager instance (owns all rate state).
    poll_interval   How often (seconds) to re-check the RPM window while
                    waiting for a slot.
    """

    def __init__(
        self,
        key_manager: KeyManager,
        poll_interval: float = 0.25,
    ) -> None:
        self._km = key_manager
        self._poll = poll_interval

    # ── async wait ─────────────────────────────────────────────────────────

    async def async_wait_for_slot(self, ks: KeyState) -> None:
        """
        Async-suspend until an RPM slot is available for *ks*.
        No-op if no RPM limit is configured.
        """
        while not self._km.check_rpm(ks):
            wait = self._km.seconds_until_rpm_slot(ks)
            await asyncio.sleep(max(wait, self._poll))

    async def async_wait_for_tpm(self, ks: KeyState, tokens: int = 0) -> None:
        """
        Async-suspend until a TPM slot is available.
        No-op if no TPM limit is configured.
        """
        while not self._km.check_tpm(ks, tokens):
            await asyncio.sleep(self._poll)

    # ── sync wait ──────────────────────────────────────────────────────────

    def sync_wait_for_slot(self, ks: KeyState) -> None:
        """
        Blocking RPM wait. Used in sync (threaded) batch mode.
        No-op if no RPM limit is configured.
        """
        while not self._km.check_rpm(ks):
            wait = self._km.seconds_until_rpm_slot(ks)
            time.sleep(max(wait, self._poll))

    def sync_wait_for_tpm(self, ks: KeyState, tokens: int = 0) -> None:
        """Blocking TPM wait."""
        while not self._km.check_tpm(ks, tokens):
            time.sleep(self._poll)