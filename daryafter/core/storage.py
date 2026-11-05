"""SQLite storage for the download list and settings.

Pass ``path=None`` for a memory-only database (private mode: nothing is written)."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path

from . import secrets
from .models import DownloadItem, State

_SCHEMA = """
CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Storage:
    def __init__(self, path: str | None, store_passwords: bool = True, readonly: bool = False):
        self.path = path
        self.persistent = path is not None
        self.store_passwords = store_passwords and self.persistent
        self._lock = threading.RLock()
        if path is None:
            self._db = sqlite3.connect(":memory:", check_same_thread=False)
        elif readonly:
            # as_uri() escapes spaces, '%' and '#' and handles Windows drive letters
            self._db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True,
                                       check_same_thread=False)
        else:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._db = sqlite3.connect(path, check_same_thread=False, timeout=10)
            try:
                self._db.execute("PRAGMA journal_mode=WAL")
                self._db.execute("PRAGMA synchronous=NORMAL")
                self._db.execute("PRAGMA secure_delete=ON")    # deleted rows are overwritten, not just unlinked
            except sqlite3.DatabaseError:
                pass
        if not readonly:
            self._db.executescript(_SCHEMA)
            self._db.commit()

    @classmethod
    def snapshot(cls, path: str) -> "Storage":
        """Read-only copy of a database file held in memory; nothing on disk is touched.
        Used by private mode to read the saved settings (including the app lock)."""
        with open(path, "rb") as fh:
            data = bytearray(fh.read())
        if len(data) > 19:
            data[18] = data[19] = 1          # header says "WAL mode"; a copy in memory can't use a WAL file
        copy = cls(None)
        copy._db.deserialize(bytes(data))
        return copy

    def scrub(self) -> None:
        """Push deleted data out of the database file: compact it and empty the journal."""
        if not self.persistent:
            return
        with self._lock:
            try:
                self._db.commit()
                self._db.execute("VACUUM")
                self._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                pass

    # ---- downloads ------------------------------------------------------
    def _encode(self, item: DownloadItem, segments: list[list] | None) -> str:
        data = item.to_dict(segments)
        password = data["options"].get("password", "")
        data["options"]["password"] = secrets.protect(password) if self.store_passwords else ""
        return json.dumps(data)

    def insert_item(self, item: DownloadItem) -> int:
        with self._lock:
            cur = self._db.execute("INSERT INTO downloads (state, created_at, data) VALUES (?, ?, ?)",
                                   (str(item.state), item.created_at, "{}"))
            item.id = int(cur.lastrowid)
            self._db.execute("UPDATE downloads SET data = ? WHERE id = ?",
                             (self._encode(item, None), item.id))
            self._db.commit()
            return item.id

    def save_item(self, item: DownloadItem, segments: list[list] | None = None) -> None:
        with self._lock:
            self._db.execute("UPDATE downloads SET state = ?, data = ? WHERE id = ?",
                             (str(item.state), self._encode(item, segments), item.id))
            self._db.commit()

    def delete_item(self, item_id: int) -> None:
        with self._lock:
            self._db.execute("DELETE FROM downloads WHERE id = ?", (item_id,))
            self._db.commit()

    def load_items(self) -> list[DownloadItem]:
        items: list[DownloadItem] = []
        with self._lock:
            rows = self._db.execute("SELECT id, data FROM downloads ORDER BY id").fetchall()
        for item_id, raw in rows:
            try:
                item = DownloadItem.from_dict(json.loads(raw))
            except Exception:
                continue
            item.id = item_id
            item.options.password = secrets.unprotect(item.options.password) if self.store_passwords else ""
            items.append(item)
        return items

    def clear_finished(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM downloads WHERE state IN (?, ?)",
                             (str(State.COMPLETED), str(State.FAILED)))
            self._db.commit()

    def clear_all(self) -> None:
        with self._lock:
            self._db.execute("DELETE FROM downloads")
            self._db.commit()

    # ---- settings -------------------------------------------------------
    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        if not self.persistent:
            return
        with self._lock:
            self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._db.commit()
                self._db.close()
            except sqlite3.Error:
                pass
