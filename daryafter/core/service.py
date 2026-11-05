"""Thread-safe front door to the engine.

The engine runs its own asyncio loop on a background thread. The UI calls these
methods from its thread; each returns a ``concurrent.futures.Future``."""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
from typing import Callable

from .manager import DownloadManager, TransportFactory
from .models import AddRequest, DownloadOptions, Event, Snapshot
from .settings import Settings
from .storage import Storage

log = logging.getLogger(__name__)


def _log_failure(future: concurrent.futures.Future) -> None:
    if not future.cancelled() and future.exception() is not None:
        log.warning("engine call failed: %r", future.exception())


class EngineService:
    def __init__(self, storage: Storage, settings: Settings, listener: Callable[[Event], None],
                 transport_factory: TransportFactory | None = None):
        self.manager = DownloadManager(storage, settings, listener, transport_factory)
        self._thread = threading.Thread(target=self._run, name="daryafter-engine", daemon=True)
        self._ready = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._startup_error: BaseException | None = None

    # ------------------------------------------------------------------ thread
    def start(self, timeout: float = 15.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("The download engine did not start")
        if self._startup_error is not None:
            raise RuntimeError(f"The download engine failed to start: {self._startup_error}")

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        try:
            loop.run_until_complete(self.manager.startup())
        except BaseException as exc:          # report instead of dying silently
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def shutdown(self, timeout: float = 20.0) -> None:
        try:
            self.submit(self.manager.shutdown()).result(timeout)
        except Exception:
            log.exception("engine shutdown problem")
        finally:
            if self._loop is not None:
                self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(5)

    def submit(self, coro) -> concurrent.futures.Future:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        future.add_done_callback(_log_failure)
        return future

    # ------------------------------------------------------------------ commands
    def probe(self, url: str, options: DownloadOptions | None = None):
        return self.submit(self.manager.probe(url, options))

    def add(self, request: AddRequest):
        return self.submit(self.manager.add(request))

    def pause(self, item_id: int):
        return self.submit(self.manager.pause(item_id))

    def resume(self, item_id: int):
        return self.submit(self.manager.resume(item_id))

    def pause_all(self):
        return self.submit(self.manager.pause_all())

    def resume_all(self):
        return self.submit(self.manager.resume_all())

    def restart(self, item_id: int):
        return self.submit(self.manager.restart(item_id))

    def remove(self, item_id: int, delete_files: bool = False):
        return self.submit(self.manager.remove(item_id, delete_files))

    def clear_completed(self):
        return self.submit(self.manager.clear_completed())

    def move_in_queue(self, item_id: int, where: str):
        return self.submit(self.manager.move_in_queue(item_id, where))

    def clear_history(self):
        return self.submit(self.manager.clear_history())

    def rename(self, item_id: int, name: str):
        return self.submit(self.manager.rename(item_id, name))

    def update_url(self, item_id: int, url: str):
        return self.submit(self.manager.update_url(item_id, url))

    def move_in_queue(self, item_id: int, where: str):
        return self.submit(self.manager.move_in_queue(item_id, where))

    def set_item_limit(self, item_id: int, bytes_per_second: int):
        return self.submit(self.manager.set_item_limit(item_id, bytes_per_second))

    def set_offline(self, offline: bool):
        return self.submit(self.manager.set_offline(offline))

    def apply_settings(self, settings: Settings) -> None:
        self._loop.call_soon_threadsafe(self.manager.apply_settings, settings)

    def snapshots(self) -> list[Snapshot]:
        return self.submit(self.manager.a_snapshots()).result(10)

    def discard_unfinished(self) -> int:
        return self.submit(_wrap(self.manager.discard_unfinished)).result(10)


async def _wrap(fn):
    return fn()
