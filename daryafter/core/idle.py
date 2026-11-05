"""How long the user has not touched the keyboard or mouse (Windows only)."""
from __future__ import annotations

import os


def system_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input anywhere in Windows; 0.0 if unknown."""
    if os.name != "nt":
        return 0.0
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0     # tick counter wraps after ~49 days
    except Exception:
        return 0.0
