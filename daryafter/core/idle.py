"""System-wide keyboard/mouse inactivity detection.

Windows: native GetLastInputInfo API.
X11: XScreenSaver extension (optional system libraries).
Wayland: the standard ``ext-idle-notify-v1`` protocol through ``libwayland-client``
(see :mod:`daryafter.core.idle_wayland`), with a GNOME Shell (Mutter) D-Bus
fallback for compositors that do not implement the protocol.
Any unsupported environment reports 0.0 (idle unknown).
"""
from __future__ import annotations

import ctypes
import os

from . import session as _session


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
    if not os.environ.get("DISPLAY"):
        return 0.0

    display = None
    info = None
    x11 = None

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


def _wayland_idle_seconds() -> float:
    """Idle seconds on Wayland, falling back only when native support is absent."""
    try:
        from . import idle_wayland
    except Exception:  # pragma: no cover - defensive import fallback
        return 0.0

    monitor = idle_wayland.monitor()
    if not monitor.available or monitor.protocol_missing:
        return _gnome_mutter_idle_seconds()

    # A pending connection or a temporary compositor disconnect is not proof
    # that Mutter is available. Avoid synchronous D-Bus calls on every poll.
    return monitor.idle_seconds()


def _gnome_mutter_idle_seconds() -> float:
    """GNOME Shell fallback: Mutter's IdleMonitor D-Bus service.

    Needs a running Qt application for the D-Bus connection (Daryafter polls
    from the GUI thread), and silently reports 0.0 anywhere else.

    The interface lives on the ``/Core`` child object (``/org/gnome/Mutter/
    IdleMonitor/Core``) in every Mutter that ships this service (3.16 through
    51, verified live against mutter 51.1); the parent path never exports the
    interface and is only tried as a last-resort candidate.
    """
    try:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

        if QCoreApplication.instance() is None:     # not from the GUI, or fake Qt in tests
            return 0.0
        bus = QDBusConnection.sessionBus()
        if not bus.isConnected():
            return 0.0

        for path in ("/org/gnome/Mutter/IdleMonitor/Core",   # the real object
                     "/org/gnome/Mutter/IdleMonitor"):       # defensive: exotic setups
            iface = QDBusInterface("org.gnome.Mutter.IdleMonitor", path,
                                   "org.gnome.Mutter.IdleMonitor", bus)
            if not iface.isValid():
                continue

            reply = iface.call("GetIdletime")
            if reply.type() != QDBusMessage.MessageType.ReplyMessage or not reply.arguments():
                continue                       # e.g. unknown interface: try the next path

            value = reply.arguments()[0]
            for _ in range(3):                          # PySide6 may nest variant levels
                if hasattr(value, "variant"):
                    value = value.variant()
                else:
                    break
            return max(int(value), 0) / 1000.0
    except Exception:
        return 0.0
    return 0.0



def system_idle_seconds() -> float:
    """Seconds since the last keyboard/mouse input, or 0.0 if unknown."""
    if os.name == "nt":
        return _windows_idle_seconds()

    kind = _session.session_type()
    if kind == _session.WAYLAND:
        return _wayland_idle_seconds()
    if kind == _session.X11:
        return _x11_idle_seconds()
    return 0.0
