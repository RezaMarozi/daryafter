"""Bandwidth limiting shared between segments (and between downloads)."""
from __future__ import annotations

import asyncio
import time


class RateLimiter:
    """Reservation-based limiter. ``rate`` is bytes/second; 0 means unlimited."""

    def __init__(self, rate: int = 0):
        self._rate = max(0, int(rate))
        self._next = 0.0

    @property
    def rate(self) -> int:
        return self._rate

    def set_rate(self, rate: int) -> None:
        self._rate = max(0, int(rate))
        self._next = min(self._next, time.monotonic() + 1.0)

    def reserve(self, nbytes: int) -> float:
        """Reserve ``nbytes``; returns how long the caller must wait first."""
        if self._rate <= 0 or nbytes <= 0:
            return 0.0
        now = time.monotonic()
        start = max(self._next, now)
        self._next = start + nbytes / self._rate
        return start - now


async def throttle(nbytes: int, *limiters: RateLimiter) -> None:
    delay = max((lim.reserve(nbytes) for lim in limiters), default=0.0)
    if delay > 0.001:
        await asyncio.sleep(delay)
