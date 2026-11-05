"""Private mode, clearing history, saved passwords, and the app lock at startup."""
import base64
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from daryafter import app
from daryafter.core.manager import DownloadManager
from daryafter.core.models import DownloadItem, DownloadOptions, State
from daryafter.core.settings import Settings
from daryafter.core.storage import Storage


def tree(folder: str) -> dict:
    """Every file under the folder with its size and modification time."""
    out = {}
    for root, _dirs, files in os.walk(folder):
        for name in files:
            p = os.path.join(root, name)
            st = os.stat(p)
            out[os.path.relpath(p, folder)] = (st.st_size, st.st_mtime_ns)
    return out


def all_bytes(folder: str) -> bytes:
    data = b""
    for root, _dirs, files in os.walk(folder):
        for name in files:
            with open(os.path.join(root, name), "rb") as fh:
                data += fh.read()
    return data


class PrivateSettingsReadTests(unittest.TestCase):
    def test_no_database_means_defaults_and_creates_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            folder = Path(d) / "does" / "not" / "exist"
            s = app.read_private_settings(folder / "daryafter.db")
            self.assertFalse(s.lock_enabled)
            self.assertFalse(folder.exists())

    def test_reads_the_lock_without_touching_the_disk(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "my folder #1 100%" / "daryafter.db"       # awkward characters on purpose
            st = Storage(str(db))
            s = Settings(theme="dark", start_private=True)
            s.set_password("secret")
            s.save(st)
            st.close()
            before = tree(d)
            loaded = app.read_private_settings(db)
            self.assertTrue(loaded.lock_enabled)
            self.assertTrue(loaded.check_password("secret"))
            self.assertEqual((loaded.theme, loaded.start_private), ("dark", True))
            self.assertEqual(tree(d), before)                         # nothing created or modified

    def test_in_memory_copy_works_too(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "daryafter.db")
            st = Storage(db)
            s = Settings()
            s.set_password("secret")
            s.save(st)
            st.close()
            before = tree(d)
            copy = Storage.snapshot(db)
            loaded = Settings.load(copy)
            copy.set_setting("app_settings", "{}")                    # a snapshot must not write back
            copy.close()
            self.assertTrue(loaded.check_password("secret"))
            self.assertEqual(tree(d), before)

    def test_sees_a_lock_that_is_still_in_the_journal(self):
        """Daryafter is running (or crashed): the newest settings are in the -wal file, not the main file."""
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "daryafter.db"
            st = Storage(str(db))
            s = Settings()
            s.set_password("secret")
            s.save(st)
            wal = Path(str(db) + "-wal")
            self.assertTrue(wal.exists() and wal.stat().st_size > 0)
            loaded = app.read_private_settings(db)               # st is still open
            st.close()
            self.assertTrue(loaded.lock_enabled)

    def test_unreadable_file_is_refused_not_treated_as_unlocked(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "daryafter.db"
            db.write_bytes(b"this is not a database " * 50)
            with self.assertRaises(app.SettingsUnreadable):
                app.read_private_settings(db)

    def test_database_without_settings_table(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "daryafter.db"
            con = sqlite3.connect(db)
            con.execute("CREATE TABLE other (x)")
            con.commit()
            con.close()
            self.assertFalse(app.read_private_settings(db).lock_enabled)

    def test_open_storage_private_is_memory_only(self):
        with tempfile.TemporaryDirectory() as d:
            saved = Settings()
            storage, settings = app.open_storage(True, saved, Path(d) / "x" / "daryafter.db")
            self.assertFalse(storage.persistent)
            storage.insert_item(DownloadItem(id=0, url="http://a/b", filename="b", directory=d))
            storage.close()
            self.assertEqual(os.listdir(d), [])


class ScrubTests(unittest.TestCase):
    def test_deleted_rows_do_not_linger_in_the_file(self):
        with tempfile.TemporaryDirectory() as d:
            st = Storage(os.path.join(d, "t.db"))
            for i in range(5):
                st.insert_item(DownloadItem(id=0, url=f"http://example.com/zz-secret-{i}.bin",
                                            filename=f"zz-secret-{i}.bin", directory=d,
                                            state=State.COMPLETED))
            self.assertIn(b"zz-secret-3", all_bytes(d))
            st.clear_all()
            st.scrub()
            self.assertNotIn(b"zz-secret", all_bytes(d))      # checked while the database is still open
            st.close()
            self.assertNotIn(b"zz-secret", all_bytes(d))


class PasswordStorageTests(unittest.IsolatedAsyncioTestCase):
    def raw_rows(self, path):
        con = sqlite3.connect(path)
        try:
            return b" ".join(r[0].encode() for r in con.execute("SELECT data FROM downloads"))
        finally:
            con.close()

    async def test_turning_remember_passwords_off_erases_them_from_disk(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "t.db")
            st = Storage(db)
            st.insert_item(DownloadItem(id=0, url="http://a/b.zip", filename="b.zip", directory=d,
                                        state=State.PAUSED, options=DownloadOptions(username="bob", password="hunter2")))
            token = base64.b64encode(b"hunter2")
            self.assertIn(token, self.raw_rows(db))                   # saved (obfuscated on Linux, DPAPI on Windows)
            m = DownloadManager(st, Settings(download_dir=d, prevent_sleep=False), lambda ev: None)
            await m.startup()
            self.assertEqual(next(iter(m.items.values())).options.password, "hunter2")
            m.apply_settings(Settings(download_dir=d, prevent_sleep=False, remember_passwords=False))
            self.assertNotIn(token, self.raw_rows(db))
            self.assertNotIn(b"hunter2", all_bytes(d))
            # still usable in this session
            self.assertEqual(next(iter(m.items.values())).options.password, "hunter2")
            await m.shutdown()
            st.close()
            st = Storage(db)
            st.store_passwords = False
            self.assertEqual(st.load_items()[0].options.password, "")
            st.close()

    async def test_private_storage_never_keeps_passwords(self):
        st = Storage(None)
        st.insert_item(DownloadItem(id=0, url="http://a/b.zip", filename="b.zip", directory="/tmp",
                                    options=DownloadOptions(password="hunter2")))
        self.assertEqual(st.load_items()[0].options.password, "")


class ClearHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_clear_history(self):
        with tempfile.TemporaryDirectory() as d:
            files = d + os.sep + "files"
            os.makedirs(files)
            for name in ("done.bin", "failed.bin.part", "paused.bin.part"):
                Path(files, name).write_bytes(b"x" * 10)
            st = Storage(os.path.join(d, "t.db"))
            for name, state in (("done.bin", State.COMPLETED), ("failed.bin", State.FAILED),
                                ("paused.bin", State.PAUSED)):
                st.insert_item(DownloadItem(id=0, url=f"http://a/zz-{name}", filename=name,
                                            directory=files, state=state, total_size=10))
            events = []
            m = DownloadManager(st, Settings(download_dir=files, prevent_sleep=False), events.append)
            await m.startup()
            count = await m.clear_history()
            self.assertEqual(count, 2)
            self.assertEqual([i.filename for i in m.items.values()], ["paused.bin"])
            self.assertEqual(sum(1 for e in events if e.kind == "removed"), 2)
            self.assertTrue(Path(files, "done.bin").exists())          # downloaded file stays
            self.assertFalse(Path(files, "failed.bin.part").exists())  # partial file of a failed one goes
            self.assertTrue(Path(files, "paused.bin.part").exists())   # paused download is kept
            await m.shutdown()
            st.close()
            raw = b"".join(Path(d, n).read_bytes() for n in os.listdir(d) if n.startswith("t.db"))
            self.assertNotIn(b"zz-done.bin", raw)
            self.assertNotIn(b"zz-failed.bin", raw)

    async def test_clear_on_exit_also_removes_failed_partials(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "failed.bin.part").write_bytes(b"x")
            st = Storage(os.path.join(d, "t.db"))
            st.insert_item(DownloadItem(id=0, url="http://a/f", filename="failed.bin", directory=d,
                                        state=State.FAILED))
            m = DownloadManager(st, Settings(download_dir=d, prevent_sleep=False, clear_history_on_exit=True),
                                lambda ev: None)
            await m.startup()
            await m.shutdown()
            self.assertFalse(Path(d, "failed.bin.part").exists())
            self.assertEqual(st.load_items(), [])
            st.close()


class PrivateStartTests(unittest.TestCase):
    def test_normal_flag_switches_the_saved_setting_off(self):
        saved = Settings(start_private=True)
        self.assertTrue(app.wants_private(app._args([]), saved))
        self.assertFalse(app.wants_private(app._args(["--normal"]), saved))
        self.assertTrue(app.wants_private(app._args(["--private"]), Settings()))
        self.assertFalse(app.wants_private(app._args([]), Settings()))

    def test_private_and_normal_together_are_refused(self):
        with self.assertRaises(SystemExit):
            app._args(["--private", "--normal"])


if __name__ == "__main__":
    unittest.main()
