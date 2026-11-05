import asyncio
import hashlib
import os
import tempfile
import time
import unittest

from daryafter.core.manager import DownloadManager
from daryafter.core.models import AddRequest, DownloadOptions, State
from daryafter.core.settings import Settings
from daryafter.core.storage import Storage

from .support import DATA, MiB, StdlibTransport, TestServer


def settings(tmp, **kw):
    s = Settings(download_dir=tmp, retry_base_delay=0.05, retry_max=6, connections=4,
                 max_concurrent=3, prevent_sleep=False, set_file_time=False,
                 auto_categorize=False)
    for k, v in kw.items():
        setattr(s, k, v)
    return s


class EngineCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.server = TestServer().start()
        self.tmp = tempfile.mkdtemp()
        self.dbpath = os.path.join(self.tmp, "db", "t.db")
        self.events = []
        self.managers = []
        self.manager = await self.make_manager()

    async def make_manager(self, **kw):
        m = DownloadManager(Storage(self.dbpath), settings(self.tmp, **kw), self.events.append,
                            lambda opts: StdlibTransport())
        await m.startup()
        self.managers.append(m)
        return m

    async def asyncTearDown(self):
        for m in self.managers:
            await m.shutdown()
        self.server.stop()

    async def add(self, path, name="out.bin", conns=4, manager=None, **opt):
        m = manager or self.manager
        options = DownloadOptions(connections=conns, **opt)
        return await m.add(AddRequest(url=self.server.base + path, filename=name,
                                      directory=self.tmp, use_category_folder=False, options=options))

    async def wait_for(self, item_id, states, timeout=30, manager=None):
        m = manager or self.manager
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            item = m.items[item_id]
            if item.state in states:
                return item
            await asyncio.sleep(0.05)
        self.fail(f"timeout: state is {m.items[item_id].state} ({m.items[item_id].error})")

    def read(self, name="out.bin"):
        with open(os.path.join(self.tmp, name), "rb") as fh:
            return fh.read()


class DownloadTests(EngineCase):
    async def test_multi_segment(self):
        item_id = await self.add("/slow.bin")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/slow.bin"])
        self.assertGreaterEqual(self.server.max_active, 3)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "out.bin.part")))

    async def test_redirect(self):
        item_id = await self.add("/redirect")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/file.bin"])

    async def test_no_range_server(self):
        item_id = await self.add("/norange.bin")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertFalse(item.resumable)
        self.assertEqual(self.read(), DATA["/norange.bin"])

    async def test_unknown_size(self):
        item_id = await self.add("/unknown.bin")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/unknown.bin"])

    async def test_tiny_file(self):
        item_id = await self.add("/tiny.bin")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), b"hello")

    async def test_flaky_server_is_retried(self):
        self.server.drops_left = 4
        item_id = await self.add("/flaky.bin")
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/flaky.bin"])
        self.assertEqual(self.server.drops_left, 0)

    async def test_connection_limit_503(self):
        item_id = await self.add("/limit.bin", conns=6)
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/limit.bin"])

    async def test_probe_filename_from_header(self):
        probe = await self.manager.probe(self.server.base + "/cd.bin")
        self.assertEqual(probe.filename, "فایل test.bin")
        self.assertEqual(probe.total_size, 100_000)
        self.assertTrue(probe.resumable)

    async def test_gone_then_refresh_link(self):
        item_id = await self.add("/gone")
        item = await self.wait_for(item_id, {State.FAILED})
        self.assertIn("410", item.error)
        await self.manager.update_url(item_id, self.server.base + "/file.bin")
        await self.manager.resume(item_id)
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/file.bin"])

    async def test_hash_ok_and_mismatch(self):
        good = hashlib.sha256(DATA["/tiny.bin"]).hexdigest()
        a = await self.add("/tiny.bin", name="a.bin", expected_hash=good, expected_hash_algo="sha256")
        b = await self.add("/tiny.bin", name="b.bin", expected_hash="0" * 64)
        ia = await self.wait_for(a, {State.COMPLETED, State.FAILED})
        ib = await self.wait_for(b, {State.COMPLETED, State.FAILED})
        self.assertEqual(ia.state, State.COMPLETED, ia.error)
        self.assertEqual(ib.state, State.FAILED)
        self.assertIn("Checksum mismatch", ib.error)

    async def test_existing_name_gets_number(self):
        with open(os.path.join(self.tmp, "out.bin"), "wb") as fh:
            fh.write(b"x")
        item_id = await self.add("/tiny.bin")
        self.assertEqual(self.manager.items[item_id].filename, "out (1).bin")


class ResumeTests(EngineCase):
    async def test_pause_and_resume(self):
        item_id = await self.add("/slow.bin")
        item = self.manager.items[item_id]
        end = time.monotonic() + 20
        while item.received < 600_000 and time.monotonic() < end:
            await asyncio.sleep(0.05)
        await self.manager.pause(item_id)
        self.assertEqual(item.state, State.PAUSED)
        saved = item.downloaded
        self.assertGreater(saved, 0)
        self.assertLess(saved, len(DATA["/slow.bin"]))
        self.assertTrue(os.path.exists(item.part_path))
        before = len(self.server.requests_for("/slow.bin"))
        await self.manager.resume(item_id)
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/slow.bin"])
        later = self.server.requests_for("/slow.bin")[before:]
        starts = [int(r.split("=")[1].split("-")[0]) for r in later if r]
        self.assertTrue(any(s > 0 for s in starts), starts)

    async def test_resume_after_restart(self):
        item_id = await self.add("/slow.bin")
        item = self.manager.items[item_id]
        end = time.monotonic() + 20
        while item.received < 600_000 and time.monotonic() < end:
            await asyncio.sleep(0.05)
        await self.manager.shutdown()
        self.managers.remove(self.manager)
        m2 = await self.make_manager()
        again = m2.items[item_id]
        self.assertEqual(again.state, State.PAUSED)
        self.assertGreater(again.downloaded, 0)
        await m2.resume(item_id)
        again = await self.wait_for(item_id, {State.COMPLETED, State.FAILED}, manager=m2)
        self.assertEqual(again.state, State.COMPLETED, again.error)
        self.assertEqual(self.read(), DATA["/slow.bin"])

    async def test_changed_file_restarts(self):
        item_id = await self.add("/changing.bin")
        item = self.manager.items[item_id]
        end = time.monotonic() + 20
        while item.received < 500_000 and time.monotonic() < end:
            await asyncio.sleep(0.05)
        await self.manager.pause(item_id)
        self.server.version = 2
        await self.manager.resume(item_id)
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/changing2.bin"])


class LimitAndStatsTests(EngineCase):
    async def test_speed_limit_and_stats(self):
        item_id = await self.add("/file.bin", speed_limit=3 * MiB)
        start = time.monotonic()
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED}, timeout=40)
        elapsed = time.monotonic() - start
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertGreater(elapsed, 1.5)
        self.assertLess(item.avg_speed, 4.2 * MiB)
        self.assertGreater(item.avg_speed, 1.5 * MiB)
        self.assertGreaterEqual(item.max_speed, item.min_speed)
        self.assertGreater(item.min_speed, 0)

    async def test_global_limit(self):
        self.manager.settings.global_speed_limit = 3 * MiB
        self.manager.global_limiter.set_rate(3 * MiB)
        item_id = await self.add("/file.bin")
        start = time.monotonic()
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED}, timeout=40)
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertGreater(time.monotonic() - start, 1.5)


class OfflineTests(EngineCase):
    async def test_offline_pauses_and_resumes(self):
        item_id = await self.add("/slow.bin")
        item = self.manager.items[item_id]
        end = time.monotonic() + 20
        while item.received < 300_000 and time.monotonic() < end:
            await asyncio.sleep(0.05)
        await self.manager.set_offline(True)
        self.assertEqual(item.state, State.PAUSED)
        count = len(self.server.log)
        await asyncio.sleep(0.5)
        self.assertEqual(len(self.server.log), count)       # no connections while offline
        with self.assertRaises(Exception):
            await self.manager.probe(self.server.base + "/file.bin")
        await self.manager.set_offline(False)
        item = await self.wait_for(item_id, {State.COMPLETED, State.FAILED})
        self.assertEqual(item.state, State.COMPLETED, item.error)
        self.assertEqual(self.read(), DATA["/slow.bin"])


class QueueTests(EngineCase):
    async def test_concurrency_limit(self):
        ids = [await self.add("/slow.bin", name=f"f{i}.bin", conns=1) for i in range(5)]
        await asyncio.sleep(0.4)
        running = [i for i in ids if self.manager.items[i].state in (State.CONNECTING, State.DOWNLOADING)]
        self.assertEqual(len(running), 3)
        for i in ids:
            item = await self.wait_for(i, {State.COMPLETED, State.FAILED}, timeout=60)
            self.assertEqual(item.state, State.COMPLETED, item.error)


if __name__ == "__main__":
    unittest.main()
