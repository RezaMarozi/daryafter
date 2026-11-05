"""Disk access for downloads: positional writes on one dedicated thread."""
from __future__ import annotations

import asyncio
import os
import shutil
from concurrent.futures import ThreadPoolExecutor

from .errors import DiskError


def disk_free(path: str) -> int | None:
    try:
        probe = path
        while probe and not os.path.exists(probe):
            parent = os.path.dirname(probe)
            if parent == probe:
                break
            probe = parent
        return shutil.disk_usage(probe or ".").free
    except OSError:
        return None


class FileWriter:
    """Writes at arbitrary offsets of one file. All writes run on a single
    thread so the file handle is never used concurrently."""

    def __init__(self, path: str):
        self.path = path
        self._fh = None
        self._write_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sg-write")
        self._sync_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sg-sync")

    async def open(self, size: int = 0) -> None:
        await self._run(self._write_pool, self._open, size)

    def _open(self, size: int) -> None:
        mode = "r+b" if os.path.exists(self.path) else "w+b"
        self._fh = open(self.path, mode, buffering=0)
        if size > 0 and os.fstat(self._fh.fileno()).st_size != size:
            self._fh.truncate(size)

    async def write_at(self, offset: int, data: bytes) -> None:
        await self._run(self._write_pool, self._write, offset, data)

    def _write(self, offset: int, data: bytes) -> None:
        fh = self._fh
        fh.seek(offset)
        view = memoryview(data)
        while view:
            written = fh.write(view)
            view = view[written:]

    async def sync(self) -> None:
        """Force written data to disk (runs on its own thread, doesn't block writes)."""
        if self._fh is not None:
            await self._run(self._sync_pool, self._sync)

    def _sync(self) -> None:
        if self._fh is not None:
            os.fsync(self._fh.fileno())

    async def aclose(self) -> None:
        if self._fh is not None:
            try:
                await self._run(self._write_pool, self._close)
            finally:
                self._fh = None
        self._write_pool.shutdown(wait=False)
        self._sync_pool.shutdown(wait=False)

    def _close(self) -> None:
        if self._fh is not None:
            self._fh.close()

    @staticmethod
    async def _run(pool: ThreadPoolExecutor, fn, *args):
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(pool, fn, *args)
        except OSError as exc:
            raise DiskError(f"Disk error: {exc.strerror or exc}") from exc
