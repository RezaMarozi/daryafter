"""Prevent system sleep while downloads are running."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)

_inhibitor: subprocess.Popen | None = None


def set_keep_awake(enabled: bool) -> None:
    """Keep the system awake while downloads are active."""
    global _inhibitor

    if os.name == "nt":
        try:
            import ctypes

            continuous = 0x80000000
            system_required = 0x00000001
            func = ctypes.windll.kernel32.SetThreadExecutionState
            func.argtypes = [ctypes.c_uint]
            func(continuous | (system_required if enabled else 0))
        except Exception:
            log.exception("Could not update Windows power state")
        return

    if enabled:
        if _inhibitor is not None and _inhibitor.poll() is None:
            return

        executable = shutil.which("systemd-inhibit")
        if executable is None:
            log.warning("systemd-inhibit is unavailable; sleep prevention disabled")
            return

        try:
            _inhibitor = subprocess.Popen(
                [
                    executable,
                    "--what=sleep",
                    "--who=Daryafter",
                    "--why=Downloads are active",
                    "--mode=block",
                    "sleep",
                    "infinity",
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            _inhibitor = None
            log.exception("Could not start sleep inhibitor")

    elif _inhibitor is not None:
        process = _inhibitor
        _inhibitor = None

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
