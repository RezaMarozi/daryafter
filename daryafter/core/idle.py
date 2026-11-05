"""System-wide keyboard/mouse inactivity detection.

Windows: native GetLastInputInfo API.
X11: XScreenSaver extension (optional system libraries).
Other environments, including Wayland: 0.0 if unsupported.
"""
from __future__ import annotations

import ctypes
import os


def _windows_idle_seconds() -> float:
    try:
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("dwTime", wintypes.DWORD),
            ]

        info = LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)

        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0

        now = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((now - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return 0.0


def _x11_idle_seconds() -> float:
    if os.environ.get("XDG_SESSION_TYPE", "").lower() != "x11":
        return 0.0

    if not os.environ.get("DISPLAY"):
        return 0.0

    display = None
    info = None

    try:
        class XScreenSaverInfo(ctypes.Structure):
            _fields_ = [
                ("window", ctypes.c_ulong),
                ("state", ctypes.c_int),
                ("kind", ctypes.c_int),
                ("til_or_since", ctypes.c_ulong),
                ("idle", ctypes.c_ulong),
                ("event_mask", ctypes.c_ulong),
            ]

        x11 = ctypes.CDLL("libX11.so.6")
        xss = ctypes.CDLL("libXss.so.1")

        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XOpenDisplay.restype = ctypes.c_void_p

        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong

        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XCloseDisplay.restype = ctypes.c_int

        x11.XFree.argtypes = [ctypes.c_void_p]
        x11.XFree.restype = ctypes.c_int

        xss.XScreenSaverAllocInfo.argtypes = []
        xss.XScreenSaverAllocInfo.restype = ctypes.POINTER(XScreenSaverInfo)

        xss.XScreenSaverQueryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(XScreenSaverInfo),
        ]
        xss.XScreenSaverQueryInfo.restype = ctypes.c_int

        display = x11.XOpenDisplay(None)
        if not display:
            return 0.0

        info = xss.XScreenSaverAllocInfo()
        if not info:
            return 0.0

        root = x11.XDefaultRootWindow(display)

        if not xss.XScreenSaverQueryInfo(display, root, info):
            return 0.0

        return info.contents.idle / 1000.0

    except Exception:
        return 0.0

    finally:
        if info:
            try:
                x11.XFree(info)
            except Exception:
                pass

        if display:
            try:
                x11.XCloseDisplay(display)
            except Exception:
                pass


def system_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input, or 0.0 if unknown."""
    if os.name == "nt":
        return _windows_idle_seconds()

    return _x11_idle_seconds()
