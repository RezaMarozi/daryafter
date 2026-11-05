"""Turn exceptions into short messages for people."""
from __future__ import annotations


def friendly(exc: BaseException) -> str:
    text = str(exc).strip()
    return text or type(exc).__name__
