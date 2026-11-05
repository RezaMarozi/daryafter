"""Keep Windows awake while downloads are running."""
from __future__ import annotations

import os


def set_keep_awake(enabled: bool) -> None:
    """Must be called from the same (long-lived) thread each time."""
    if os.name != "nt":
        return
    try:
        import ctypes

        es_continuous, es_system_required = 0x80000000, 0x00000001
        func = ctypes.windll.kernel32.SetThreadExecutionState
        func.argtypes = [ctypes.c_uint]
        func(es_continuous | (es_system_required if enabled else 0))
    except Exception:
        pass
