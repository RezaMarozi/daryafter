"""Timers: do something at a given time of day. No GUI in here, so it can be tested without Qt.

Actions:
  start       go online (if offline) and resume every paused / failed download
  stop        pause every download
  disconnect  go offline: nothing is downloaded until a "start" rule or the Go-online button

A rule fires only while Daryafter is running. If the computer was asleep through the time, the rule
still fires when it wakes up, but only if that is within ``max_late`` seconds of the planned time."""
from __future__ import annotations

import time as _time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timedelta
from typing import Callable

START, STOP, DISCONNECT = "start", "stop", "disconnect"
ACTIONS = (START, STOP, DISCONNECT)
ALL_DAYS = [0, 1, 2, 3, 4, 5, 6]          # Monday = 0 ... Sunday = 6


@dataclass
class Rule:
    action: str = START
    hour: int = 0
    minute: int = 0
    days: list[int] = field(default_factory=lambda: list(ALL_DAYS))
    once: bool = False                    # fire one time, then switch itself off
    enabled: bool = True
    index: int = -1                       # position in settings.schedule (not saved)

    def to_dict(self) -> dict:
        data = asdict(self)
        del data["index"]
        return data

    @classmethod
    def from_dict(cls, data, index: int = -1) -> "Rule | None":
        """Returns None for anything that isn't a usable rule, so bad settings can't crash the app."""
        if not isinstance(data, dict) or data.get("action") not in ACTIONS:
            return None
        try:
            hour, minute = int(data.get("hour", 0)), int(data.get("minute", 0))
            days = sorted({int(d) for d in data.get("days", ALL_DAYS) if 0 <= int(d) <= 6})
        except (TypeError, ValueError):
            return None
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return cls(data["action"], hour, minute, days, bool(data.get("once", False)),
                   bool(data.get("enabled", True)), index)

    def clock_text(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"


def rules_from_settings(settings) -> list[Rule]:
    rules = (Rule.from_dict(d, i) for i, d in enumerate(settings.schedule or []))
    return [r for r in rules if r is not None]


class Scheduler:
    """Call ``due(rules)`` every few seconds; it returns the rules whose time has just passed."""

    def __init__(self, clock: Callable[[], datetime] = datetime.now, max_late: float = 600.0):
        self._clock = clock
        self.max_late = max_late
        self._last: datetime | None = None

    def due(self, rules: list[Rule], now: datetime | None = None) -> list[Rule]:
        now = now or self._clock()
        last, self._last = self._last, now
        if last is None or now < last:                 # first call, or the clock was turned back
            return []
        found: list[tuple[datetime, Rule]] = []
        day = last.date()
        while day <= now.date():
            for rule in rules:
                if not rule.enabled or day.weekday() not in rule.days:
                    continue
                when = datetime.combine(day, time(rule.hour, rule.minute))
                if last < when <= now and (now - when).total_seconds() <= self.max_late:
                    found.append((when, rule))
            day += timedelta(days=1)
        found.sort(key=lambda pair: pair[0])
        return [rule for _when, rule in found]

    def next_run(self, rules: list[Rule], now: datetime | None = None) -> tuple[datetime, Rule] | None:
        """The next time any enabled rule will fire (for showing it in the window)."""
        now = now or self._clock()
        best: tuple[datetime, Rule] | None = None
        for offset in range(0, 8):
            day = now.date() + timedelta(days=offset)
            for rule in rules:
                if not rule.enabled or day.weekday() not in rule.days:
                    continue
                when = datetime.combine(day, time(rule.hour, rule.minute))
                if when > now and (best is None or when < best[0]):
                    best = (when, rule)
        return best
