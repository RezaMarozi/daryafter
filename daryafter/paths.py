"""Where the app keeps its data. Portable mode keeps everything next to the app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .branding import APP_NAME


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def is_portable() -> bool:
    return bool(os.environ.get("DARYAFTER_PORTABLE")) or (app_root() / "portable.flag").exists()


def data_dir() -> Path:
    """Folder for the database and logs. Not created here."""
    override = os.environ.get("DARYAFTER_DATA")
    if override:
        return Path(override)
    if is_portable():
        return app_root() / "data"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / APP_NAME.lower()


def default_download_dir() -> Path:
    return Path.home() / "Downloads"


def assets_dir() -> Path:
    return Path(__file__).resolve().parent / "assets"


def locales_dir() -> Path:
    return Path(__file__).resolve().parent / "locales"
