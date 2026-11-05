import asyncio
import os
import tempfile
import time
import unittest

from daryafter.core.categories import category_for
from daryafter.core.filenames import (parse_content_disposition, resolve_filename,
                                     sanitize_filename, unique_name)
from daryafter.core.job import plan_segments
from daryafter.core.limiter import RateLimiter
from daryafter.core.probe import parse_content_range
from daryafter.core.settings import Settings
from daryafter.core.speed import SpeedMeter


class FilenameTests(unittest.TestCase):
    def test_sanitize(self):
        self.assertEqual(sanitize_filename('a<b>:c?.txt'), "a_b__c_.txt")
        self.assertEqual(sanitize_filename("CON.txt"), "_CON.txt")
        self.assertEqual(sanitize_filename("  name. "), "name")
        self.assertEqual(sanitize_filename(""), "download")
        self.assertEqual(sanitize_filename("evil\u202egnp.exe"), "evilgnp.exe")
        self.assertLessEqual(len(sanitize_filename("x" * 400 + ".zip")), 180)

    def test_content_disposition(self):
        self.assertEqual(parse_content_disposition('attachment; filename="a b.zip"'), "a b.zip")
        self.assertEqual(parse_content_disposition("attachment; filename=a.zip; size=3"), "a.zip")
        self.assertEqual(parse_content_disposition("attachment; filename*=UTF-8''%D9%81.txt"), "ف.txt")
        self.assertEqual(parse_content_disposition('attachment; filename="%D9%81.txt"'), "ف.txt")
        self.assertIsNone(parse_content_disposition("inline"))

    def test_resolve(self):
        self.assertEqual(resolve_filename("http://x.com/a/b%20c.zip"), "b c.zip")
        self.assertEqual(resolve_filename("http://x.com/", content_type="text/html"), "index.html")
        self.assertEqual(resolve_filename("http://x.com/get", content_type="application/pdf"), "get.pdf")
        self.assertEqual(resolve_filename("http://x.com/get", content_disposition='attachment; filename="r.7z"'), "r.7z")

    def test_unique(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "a.tar.gz"), "w").close()
            self.assertEqual(unique_name(d, "a.tar.gz"), "a (1).tar.gz")
            self.assertEqual(unique_name(d, "b.txt"), "b.txt")

    def test_category(self):
        self.assertEqual(category_for("x.MKV"), "Video")
        self.assertEqual(category_for("x.unknown"), "Other")


class MiscTests(unittest.TestCase):
    def test_plan_segments(self):
        segs = plan_segments(10 << 20, True, 4)
        self.assertEqual(len(segs), 4)
        self.assertEqual(segs[0].start, 0)
        self.assertEqual(segs[-1].end, 10 << 20)
        for a, b in zip(segs, segs[1:]):
            self.assertEqual(a.end, b.start)
        self.assertEqual(len(plan_segments(1 << 20, True, 8)), 1)
        self.assertEqual(len(plan_segments(50 << 20, False, 8)), 1)
        self.assertIsNone(plan_segments(-1, True, 8)[0].end)
        self.assertTrue(plan_segments(0, True, 8)[0].done)

    def test_content_range(self):
        cr = parse_content_range("bytes 0-0/12345")
        self.assertEqual((cr.start, cr.end, cr.total), (0, 0, 12345))
        self.assertIsNone(parse_content_range("bytes 0-0/*").total)
        self.assertEqual(parse_content_range("bytes */77").total, 77)
        self.assertIsNone(parse_content_range("garbage"))

    def test_speed_meter(self):
        m = SpeedMeter()
        m.reset(0.0)
        m.add(1000)
        self.assertAlmostEqual(m.sample(1.0), 1000, delta=1)
        m.add(3000)
        self.assertAlmostEqual(m.sample(2.0), 3000, delta=1)

    def test_password(self):
        s = Settings()
        self.assertTrue(s.check_password("anything"))
        s.set_password("secret")
        self.assertTrue(s.lock_enabled)
        self.assertTrue(s.check_password("secret"))
        self.assertFalse(s.check_password("wrong"))
        s.set_password("")
        self.assertFalse(s.lock_enabled)


class LimiterTests(unittest.IsolatedAsyncioTestCase):
    async def test_limiter_rate(self):
        lim = RateLimiter(100_000)
        start = time.monotonic()
        for _ in range(10):
            await asyncio.sleep(max(0, lim.reserve(10_000)))
        self.assertAlmostEqual(time.monotonic() - start, 0.9, delta=0.2)


if __name__ == "__main__":
    unittest.main()


class CliTests(unittest.IsolatedAsyncioTestCase):
    async def test_cli_downloads_and_reports(self):
        import contextlib
        import io

        from daryafter import cli
        from daryafter.core.fmt import human_size, human_time

        from .support import DATA, StdlibTransport, TestServer

        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_time(75), "01:15")
        server = TestServer().start()
        try:
            with tempfile.TemporaryDirectory() as d:
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = await cli.run([server.base + "/cd.bin", "-o", d, "-n", "mine.bin", "-y"],
                                         transport_factory=lambda o: StdlibTransport())
                self.assertEqual(code, 0, out.getvalue())
                with open(os.path.join(d, "mine.bin"), "rb") as fh:
                    self.assertEqual(fh.read(), DATA["/cd.bin"])
                self.assertIn("Average", out.getvalue())
        finally:
            server.stop()
