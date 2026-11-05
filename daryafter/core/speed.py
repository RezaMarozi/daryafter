"""Live speed measurement."""
from __future__ import annotations

from collections import deque


class SpeedMeter:
    """Counts bytes and reports the average speed over a sliding window."""

    def __init__(self, window: float = 1.0):
        self.window = window
        self.total = 0
        self.speed = 0.0
        self._samples: deque[tuple[float, int]] = deque()

    def add(self, nbytes: int) -> None:
        self.total += nbytes

    def reset(self, now: float) -> None:
        self.speed = 0.0
        self._samples.clear()
        self._samples.append((now, self.total))

    def sample(self, now: float) -> float:
        self._samples.append((now, self.total))
        while len(self._samples) >= 2 and self._samples[1][0] <= now - self.window:
            self._samples.popleft()
        t0, b0 = self._samples[0]
        dt = now - t0
        if dt > 0.05:
            self.speed = (self.total - b0) / dt
        return self.speed
