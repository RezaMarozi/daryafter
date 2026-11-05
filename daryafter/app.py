"""Program entry point."""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

from .branding import APP_ID, APP_NAME, ORG_NAME
from .core.models import State
from .core.service import EngineService
from .core.settings import Settings
from .core.storage import Storage
from .i18n import set_language
from .paths import data_dir


def _args(argv):
    p = argparse.ArgumentParser(prog="daryafter")
    p.add_argument("url", nargs="?", default="", help="a link to add on start")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--private", action="store_true", help="private mode: keep nothing on disk")
    mode.add_argument("--normal", action="store_true",
                      help="start normally even if 'Start in private mode' is ticked in Settings")
    p.add_argument("--portable", action="store_true", help="keep data next to the program")
    p.add_argument("--data-dir", default="", help="folder for the database")
    p.add_argument("--reset-lock", action="store_true",
                   help="forgot the password: remove the lock and clear the saved list")
    return p.parse_args(argv)


def wants_private(args, saved: Settings) -> bool:
    """--private always wins; --normal switches the saved 'start in private mode' setting off for this run."""
    if args.private:
        return True
    return saved.start_private and not args.normal


class SettingsUnreadable(Exception):
    """The settings file exists but can't be read, so we can't tell if the app lock is on."""


def read_private_settings(db_path: Path) -> Settings:
    """Read the saved settings (including the app lock) without writing anything to disk.
    Private mode must go through this, otherwise it would be a way around the lock."""
    if not db_path.exists():
        return Settings()
    last: Exception | None = None
    ro = lambda: Storage(str(db_path), readonly=True)          # noqa: E731  (sees recent changes, may create -shm)
    copy = lambda: Storage.snapshot(str(db_path))              # noqa: E731  (touches nothing)
    wal = Path(str(db_path) + "-wal")
    busy = wal.exists() and wal.stat().st_size > 0               # another Daryafter is running, or crashed
    for opener in ((ro, copy) if busy else (copy, ro)):
        try:
            reader = opener()
            try:
                return Settings.load(reader)
            finally:
                reader.close()
        except sqlite3.OperationalError as exc:
            if "no such table" in str(exc):          # a database that never saved any settings
                return Settings()
            last = exc
        except (sqlite3.Error, OSError) as exc:
            last = exc
    raise SettingsUnreadable(str(last))


def open_storage(private: bool, saved: Settings, db_path: Path) -> tuple[Storage, Settings]:
    """Private mode: nothing is written. Otherwise open the database on disk."""
    if private:
        return Storage(None), saved
    storage = Storage(str(db_path))
    settings = Settings.load(storage)
    storage.store_passwords = bool(settings.remember_passwords)
    return storage, settings


def _reset_lock(db_path: Path) -> int:
    """Forgotten password: remove the lock AND the saved list, history and passwords,
    so resetting never shows anyone what was downloaded. Downloaded files are not touched."""
    from PySide6.QtWidgets import QMessageBox

    from .i18n import tr

    if not db_path.exists():
        return 0
    box = QMessageBox.question(
        None, APP_NAME,
        tr("Remove the app lock?\n\nThis also clears the saved download list, history and saved "
           "passwords. Downloaded files are not touched."),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if box != QMessageBox.StandardButton.Yes:
        return 1
    storage = Storage(str(db_path))
    for item in storage.load_items():                  # don't leave partial files with no list entry
        if item.state != State.COMPLETED:
            try:
                os.remove(item.part_path)
            except OSError:
                pass
    storage.clear_all()
    settings = Settings.load(storage)
    settings.set_password("")
    settings.save(storage)
    storage.scrub()
    storage.close()
    QMessageBox.information(None, APP_NAME, tr("The app lock was removed."))
    return 0


def _app_icon():
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

    pix = QPixmap(128, 128)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setBrush(QColor("#0B7F99"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(8, 8, 112, 112), 26, 26)
    pen = QPen(QColor("#FFFFFF"), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    arrow = QPainterPath()
    arrow.moveTo(64, 30)
    arrow.lineTo(64, 78)
    arrow.moveTo(42, 58)
    arrow.lineTo(64, 80)
    arrow.lineTo(86, 58)
    arrow.moveTo(38, 96)
    arrow.lineTo(90, 96)
    p.drawPath(arrow)
    p.end()
    return QIcon(pix)


def main(argv: list[str] | None = None) -> int:
    args = _args(sys.argv[1:] if argv is None else argv)
    if args.portable:
        os.environ["DARYAFTER_PORTABLE"] = "1"
    if args.data_dir:
        os.environ["DARYAFTER_DATA"] = args.data_dir
    db_path = data_dir() / "daryafter.db"

    from PySide6.QtWidgets import QApplication, QMessageBox

    from .ui.bridge import EngineBridge
    from .ui.main_window import MainWindow
    from .ui.theme import apply_theme

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
        except Exception:
            pass

    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    app.setWindowIcon(_app_icon())
    if args.reset_lock:
        return _reset_lock(db_path)

    try:
        saved = read_private_settings(db_path)          # read-only peek: creates nothing
    except SettingsUnreadable:
        QMessageBox.critical(None, APP_NAME,
                             f"Daryafter could not read its settings file, so it cannot tell whether "
                             f"the app lock is on.\n\n{db_path}")
        return 1
    private = wants_private(args, saved)
    if not private:
        try:
            data_dir().mkdir(parents=True, exist_ok=True)
            logging.basicConfig(filename=str(data_dir() / "daryafter.log"), level=logging.INFO,
                                format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        except OSError:
            pass
    storage, settings = open_storage(private, saved, db_path)

    set_language(settings.language)
    apply_theme(app, settings.theme)

    bridge = EngineBridge()
    service = EngineService(storage, settings, bridge.push)
    service.start()

    def save_settings(current: Settings) -> None:
        if not private:
            current.save(storage)

    window = MainWindow(service, bridge, settings, private=private, on_settings_changed=save_settings)
    window.show()
    if args.url:
        window.add_download(args.url)                   # while locked this waits for the password
    code = app.exec()

    if not private:
        settings.window_geometry = window.save_state()
        settings.save(storage)
    else:
        service.discard_unfinished()
    service.shutdown()
    storage.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
