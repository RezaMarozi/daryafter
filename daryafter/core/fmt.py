"""Human-friendly numbers."""
from __future__ import annotations


def human_size(n: float) -> str:
    if n < 0:
        return "unknown"
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def human_speed(bps: float) -> str:
    return f"{human_size(max(0.0, bps))}/s"


def human_time(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    s = int(seconds + 0.5)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"
