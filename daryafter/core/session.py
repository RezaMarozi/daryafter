"""Which kind of graphical session Daryafter runs in (X11 / Wayland / none).

Notes on the rules (they deliberately mirror how Qt itself picks its platform
plugin, so the two never disagree inside one process):

- On Windows there is no such thing as a Wayland session ("windows").
- On Linux, a Wayland session means the compositor socket is reachable through
  the environment: ``WAYLAND_DISPLAY`` (normal start; a bare socket name like
  ``wayland-1``) or ``WAYLAND_SOCKET`` (file-descriptor hand-over by the
  session manager). If either is set we say "wayland" first, because Qt would
  pick the Wayland plugin too - even when ``DISPLAY`` is also set (XWayland).
- Without those, ``XDG_SESSION_TYPE`` names the session as declared by the
  session manager: "x11", "tty"/"console", else unknown.
- As a last resort a plain ``DISPLAY`` means "probably X11".
"""
from __future__ import annotations

import os
import sys

WINDOWS = "windows"
WAYLAND = "wayland"
X11 = "x11"
TTY = "tty"
UNKNOWN = "unknown"

_SESSION_TYPES = {
    "wayland": WAYLAND,
    "x11": X11,
    "tty": TTY,
    "console": TTY,
}


def session_type(env: dict[str, str] | None = None) -> str:
    """Return the display/session kind, never empty."""
    env = os.environ if env is None else env

    if sys.platform == "win32":
        return WINDOWS

    if env.get("WAYLAND_DISPLAY") or env.get("WAYLAND_SOCKET"):
        # Qt picks its Wayland plugin in exactly this condition.
        return WAYLAND

    declared = _SESSION_TYPES.get((env.get("XDG_SESSION_TYPE") or "").strip().lower())
    if declared:
        return declared

    if env.get("DISPLAY"):
        return X11

    return UNKNOWN


def wants_wayland(env: dict[str, str] | None = None) -> bool:
    return session_type(env) == WAYLAND
