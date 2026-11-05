import os
import tempfile
import time
import unittest

from daryafter.core.models import AddRequest, DownloadOptions, State
from daryafter.core.service import EngineService
from daryafter.core.settings import Settings
from daryafter.core.storage import Storage

from .support import DATA, StdlibTransport, TestServer


class ServiceTests(unittest.TestCase):
    def test_service_from_another_thread(self):
        server = TestServer().start()
        events = []
        with tempfile.TemporaryDirectory() as d:
            settings = Settings(download_dir=d, prevent_sleep=False, auto_categorize=False)
            service = EngineService(Storage(None), settings, events.append,
                                    lambda opts: StdlibTransport())
            service.start()
            try:
                probe = service.probe(server.base + "/cd.bin").result(10)
                item_id = service.add(AddRequest(url=server.base + "/cd.bin", filename="svc.bin",
                                                 probe=probe, use_category_folder=False,
                                                 options=DownloadOptions())).result(10)
                end = time.monotonic() + 20
                while time.monotonic() < end:
                    snap = next(s for s in service.snapshots() if s.id == item_id)
                    if snap.state in (State.COMPLETED, State.FAILED):
                        break
                    time.sleep(0.05)
                self.assertEqual(snap.state, State.COMPLETED, snap.error)
                with open(os.path.join(d, "svc.bin"), "rb") as fh:
                    self.assertEqual(fh.read(), DATA["/cd.bin"])
                kinds = {e.kind for e in events}
                self.assertTrue({"added", "updated", "completed"} <= kinds, kinds)
            finally:
                service.shutdown()
                server.stop()


if __name__ == "__main__":
    unittest.main()
