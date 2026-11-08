"""Desktop notifications for sessions without a usable system-tray icon.

Uses the freedesktop notification service through the optional notify-send
utility. Everything is imported lazily to keep tests and startup lightweight.
"""
from __future__ import annotations

import logging
import shutil
import subprocess

log = logging.getLogger(__name__)


def notify_desktop(title: str, text: str, app_name: str = "Daryafter",
                   icon: str = "daryafter", timeout_ms: int = 6000) -> bool:
    """Show a desktop notification through notify-send.

    Returns True when notify-send successfully submits the notification.
    Missing utilities and failures are non-fatal.
    """
    executable = shutil.which("notify-send")
    if not executable:
        return False

    command = [
        executable,
        "--app-name", app_name,
        "--icon", icon,
        "--expire-time", str(max(0, int(timeout_ms))),
        title,
        text,
    ]

    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode == 0:
            return True

        log.debug("notify-send failed: %s", result.stderr.strip())
        return False
    except (OSError, subprocess.TimeoutExpired):
        log.debug("Could not send a desktop notification", exc_info=True)
        return False
