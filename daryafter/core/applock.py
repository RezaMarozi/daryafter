"""App lock rules with no GUI in them, so they can be tested without Qt.

The lock is a screen lock: it hides the window until the password is typed.
It does not encrypt the database or the downloaded files."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .settings import Settings

MIN_LENGTH = 4
MAX_LENGTH = 128


def check_new_password(password: str, confirm: str) -> str:
    """Returns "" when the new password is acceptable, otherwise a short English message."""
    if not password.strip():
        return "Type a password."
    if len(password) < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters."
    if len(password) > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."
    if password != confirm:
        return "The two passwords are different."
    return ""


class AttemptLimiter:
    """Slows down guessing: the first few mistakes are free, then every mistake makes the
    next try wait twice as long (5 s, 10 s, 20 s ... up to 5 minutes). Kept in memory only."""

    def __init__(self, free_tries: int = 3, base_delay: float = 5.0, max_delay: float = 300.0,
                 clock: Callable[[], float] = time.monotonic):
        self.free_tries = free_tries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._clock = clock
        self.failures = 0
        self._until = 0.0

    def wait_seconds(self) -> float:
        return max(0.0, self._until - self._clock())

    def failed(self) -> float:
        """Record a wrong password. Returns how many seconds the next try must wait."""
        self.failures += 1
        extra = self.failures - self.free_tries
        if extra >= 1:
            delay = min(self.max_delay, self.base_delay * 2 ** min(extra - 1, 20))
            self._until = self._clock() + delay
        return self.wait_seconds()

    def succeeded(self) -> None:
        self.failures = 0
        self._until = 0.0


@dataclass(frozen=True)
class UnlockResult:
    ok: bool
    wait: float = 0.0        # seconds before another try is accepted


class LockController:
    """Tracks whether the app is locked. Reads the settings object live, so changing
    the password or the options in the Settings window takes effect at once."""

    def __init__(self, settings: Settings, idle_seconds: Callable[[], float] = lambda: 0.0,
                 limiter: AttemptLimiter | None = None):
        self.settings = settings
        self.locked = False
        self.limiter = limiter or AttemptLimiter()
        self._idle_seconds = idle_seconds

    def lock(self) -> bool:
        """Lock now if a password is set. Returns True when the app is locked."""
        if self.settings.lock_enabled:
            self.locked = True
        return self.locked

    def try_unlock(self, password: str) -> UnlockResult:
        if not self.locked:
            return UnlockResult(True)
        wait = self.limiter.wait_seconds()
        if wait > 0:                       # still cooling down: don't even look at the password
            return UnlockResult(False, wait)
        if self.settings.check_password(password):
            self.locked = False
            self.limiter.succeeded()
            return UnlockResult(True)
        return UnlockResult(False, self.limiter.failed())

    def inactivity_expired(self) -> bool:
        minutes = self.settings.lock_after_minutes
        return (self.settings.lock_enabled and not self.locked and minutes > 0
                and self._idle_seconds() >= minutes * 60)
