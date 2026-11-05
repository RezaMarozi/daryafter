"""One download, from the first probe to the finished file."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import random
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from typing import Callable

from .diskio import FileWriter, disk_free
from .errors import (DiskError, DownloadError, FatalError, HttpStatusError, NetworkError,
                     Requeue, ServerChangedError)
from .filenames import unique_name
from .hashing import guess_algorithm, hash_file
from .limiter import RateLimiter, throttle
from .models import DownloadItem, DownloadOptions, ProbeResult, Segment, Snapshot, State, make_snapshot
from .probe import parse_content_range, probe_url, status_error
from .settings import Settings
from .speed import SpeedMeter
from .transport import Transport

log = logging.getLogger(__name__)

MIN_SEGMENT = 1 << 20          # first split never makes segments smaller than 1 MiB
MIN_SPLIT = 2 << 20            # a running segment is only split if >= 2 MiB remain
FLUSH_SIZE = 256 << 10         # buffer per segment before writing to disk
CHECKPOINT_EVERY = 3.0         # seconds between "safe to resume from here" saves
MAX_CONNECTIONS = 32
WARMUP_SECONDS = 1.0           # ignore the ramp-up when recording min/max speed


class _Abort(Exception):
    pass


def plan_segments(total: int, resumable: bool, connections: int) -> list[Segment]:
    """Split the file into equal parts, one per connection."""
    if total == 0:
        return [Segment(0, 0, 0)]
    if total < 0:
        return [Segment(0, None, 0)]
    if not resumable or connections <= 1 or total < 2 * MIN_SEGMENT:
        return [Segment(0, total, 0)]
    count = max(1, min(connections, total // MIN_SEGMENT))
    size = total // count
    segments = []
    for i in range(count):
        start = i * size
        end = total if i == count - 1 else start + size
        segments.append(Segment(start, end, start))
    return segments


def build_headers(opts: DownloadOptions, settings: Settings) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Accept-Encoding": "identity",     # raw bytes, so byte ranges stay exact
        "User-Agent": opts.user_agent or settings.user_agent,
    }
    if opts.referer:
        headers["Referer"] = opts.referer
    if opts.cookies:
        headers["Cookie"] = opts.cookies
    headers.update(opts.headers)
    return headers


@dataclass
class JobEnv:
    settings: Settings
    global_limiter: RateLimiter
    make_transport: Callable[[DownloadOptions], Transport]
    save: Callable[[DownloadItem, list | None], None]      # persist progress
    changed: Callable[[DownloadItem], None]                # state changed -> persist + notify


class DownloadJob:
    def __init__(self, item: DownloadItem, env: JobEnv):
        self.item = item
        self.env = env
        self.meter = SpeedMeter()
        self.limiter = RateLimiter(0 if item.options.max_speed else item.options.speed_limit)
        self.speed = 0.0
        self.eta: float | None = None
        self.message = ""            # transient, e.g. "retrying in 4s"
        self.note = ""               # sticky until the job ends
        self.retries = 0
        self.verify_progress = 0.0
        self.stop_reason = ""
        self._task: asyncio.Task | None = None
        self._workers: dict[asyncio.Task, Segment] = {}
        self._writer: FileWriter | None = None
        self._transport: Transport | None = None
        self._headers: dict[str, str] = {}
        self._cap = 1
        self._fallback_used = False
        self._last_tick: float | None = None
        self._run_active = 0.0
        self._base_session = item.session_bytes
        self._ema = 0.0
        self._last_ckpt = time.monotonic()
        self._ckpt_busy = False
        self._ckpt_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ control
    def start(self) -> asyncio.Task:
        self._task = asyncio.get_running_loop().create_task(self._main(), name=f"job-{self.item.id}")
        return self._task

    @property
    def task(self) -> asyncio.Task | None:
        return self._task

    @property
    def active(self) -> bool:
        return self._task is not None and not self._task.done()

    async def stop(self, reason: str = "pause") -> None:
        self.stop_reason = reason
        task = self._task
        if task is not None and not task.done():
            task.cancel()
            await asyncio.wait({task})

    def snapshot(self) -> Snapshot:
        running = self.item.state == State.DOWNLOADING
        return make_snapshot(self.item, speed=self.speed if running else 0.0,
                             eta=self.eta if running else None,
                             message=self.message or self.note, connections=len(self._workers),
                             verify_progress=self.verify_progress)

    # ------------------------------------------------------------------ ticking
    def tick(self, now: float) -> None:
        """Called about twice a second by the manager while the job runs."""
        it = self.item
        if it.state != State.DOWNLOADING or self._last_tick is None:
            self.speed = 0.0
            return
        self._accrue(now)
        self.speed = self.meter.sample(now)
        self._ema = self.speed if self._ema <= 0 else 0.7 * self._ema + 0.3 * self.speed
        it.session_bytes = self._base_session + self.meter.total
        if it.total_size > 0 and self._ema > 1:
            self.eta = max(0.0, (it.total_size - it.received) / self._ema)
        else:
            self.eta = None
        if self._run_active >= WARMUP_SECONDS:
            it.max_speed = max(it.max_speed, self.speed)
            it.min_speed = self.speed if it.min_speed < 0 else min(it.min_speed, self.speed)
        if now - self._last_ckpt >= CHECKPOINT_EVERY and not self._ckpt_busy:
            self._ckpt_busy = True
            self._last_ckpt = now
            self._ckpt_task = asyncio.get_running_loop().create_task(self._checkpoint())

    def _accrue(self, now: float) -> None:
        if self._last_tick is not None:
            dt = max(0.0, now - self._last_tick)
            self.item.active_seconds += dt
            self._run_active += dt
            self._last_tick = now

    def _begin_active(self) -> None:
        now = time.monotonic()
        self._last_tick = now
        self._run_active = 0.0
        self._base_session = self.item.session_bytes
        self.meter = SpeedMeter()
        self.meter.reset(now)
        self._ema = 0.0

    def _end_active(self) -> None:
        if self._last_tick is not None:
            self._accrue(time.monotonic())
            self._last_tick = None
            self.item.session_bytes = self._base_session + self.meter.total
        self.speed = 0.0
        self.eta = None

    async def _checkpoint(self) -> None:
        try:
            segments = [s.to_list() for s in self.item.segments]    # positions before the sync
            if self._writer is not None:
                await self._writer.sync()
            self.item.session_bytes = self._base_session + self.meter.total
            self.env.save(self.item, segments)
        except Exception:
            log.warning("checkpoint failed", exc_info=True)
        finally:
            self._ckpt_busy = False

    async def _drain_checkpoint(self) -> None:
        task = self._ckpt_task
        if task is not None and not task.done():
            await asyncio.wait({task})

    # ------------------------------------------------------------------ main flow
    def _set_state(self, state: State) -> None:
        self.item.state = state
        self.env.changed(self.item)

    async def _main(self) -> None:
        it = self.item
        try:
            self._set_state(State.CONNECTING)
            await self._prepare()
            self._set_state(State.DOWNLOADING)
            self._begin_active()
            await self._download()
            self._end_active()
            await self._finalize()
        except asyncio.CancelledError:
            self._end_active()
            await self._after_stop()
        except DownloadError as exc:
            self._end_active()
            await self._after_failure(exc)
        except Exception as exc:               # a bug, not a network problem
            log.exception("unexpected error in download %s", it.id)
            self._end_active()
            await self._after_failure(FatalError(f"Unexpected error: {exc}"))
        finally:
            await self._close_resources()

    # ---- preparation ------------------------------------------------------
    def _build_headers(self) -> dict[str, str]:
        return build_headers(self.item.options, self.env.settings)

    def _max_retries(self) -> int:
        return int(self.env.settings.retry_max)

    def _target_connections(self) -> int:
        opts = self.item.options
        wanted = MAX_CONNECTIONS if opts.max_speed else opts.connections
        return max(1, min(MAX_CONNECTIONS, int(wanted)))

    async def _probe_with_retries(self) -> ProbeResult:
        attempts = 0
        while True:
            try:
                return await probe_url(self._transport, self.item.url, self._headers)
            except DownloadError as exc:
                if not exc.retryable:
                    raise
                attempts += 1
                if 0 <= self._max_retries() < attempts:
                    raise
                await self._backoff(attempts, exc)

    def _resume_blocker(self, probe: ProbeResult) -> str:
        it = self.item
        if not probe.resumable:
            return "The server doesn't support resuming, so the download restarted"
        if probe.total_size != it.total_size:
            return "The file on the server changed, so the download restarted"
        for old, new in ((it.etag, probe.etag), (it.last_modified, probe.last_modified)):
            if old and new and old != new and not old.startswith("W/") and not new.startswith("W/"):
                return "The file on the server changed, so the download restarted"
        return ""

    def _reset_progress(self, reason: str) -> None:
        self.note = reason
        log.info("download %s: %s", self.item.id, reason)
        self.item.segments = []
        with contextlib.suppress(OSError):
            os.remove(self.item.part_path)

    def _segments_valid(self) -> bool:
        it = self.item
        segs = it.segments
        if not segs or segs[0].start != 0:
            return False
        for seg in segs:
            if seg.pos < seg.start or (seg.end is not None and seg.pos > seg.end):
                return False
        for a, b in zip(segs, segs[1:]):
            if a.end != b.start:
                return False
        if it.total_size > 0:
            return segs[-1].end == it.total_size
        if it.total_size == 0:
            return len(segs) == 1 and segs[0].end == 0
        return len(segs) == 1 and segs[0].end is None

    async def _prepare(self) -> None:
        it = self.item
        it.error = ""
        self._transport = self.env.make_transport(it.options)
        self._headers = self._build_headers()
        probe = await self._probe_with_retries()
        it.final_url = probe.final_url

        if it.downloaded == 0:
            it.segments = []
        else:
            reason = self._resume_blocker(probe)
            if reason:
                self._reset_progress(reason)
        it.total_size = probe.total_size
        it.resumable = probe.resumable
        it.etag, it.last_modified = probe.etag, probe.last_modified
        it.content_type = probe.content_type or it.content_type

        try:
            os.makedirs(it.directory, exist_ok=True)
        except OSError as exc:
            raise DiskError(f"Can't create the folder: {exc.strerror or exc}") from exc

        if it.downloaded > 0 and not os.path.exists(it.part_path):
            self._reset_progress("The partial file was missing, so the download restarted")
        if it.segments and not self._segments_valid():
            self._reset_progress("Saved progress was invalid, so the download restarted")

        have = os.path.getsize(it.part_path) if os.path.exists(it.part_path) else 0
        need = max(0, it.total_size - have) if it.total_size > 0 else 0
        free = disk_free(it.directory)
        if need and free is not None and free < need + (16 << 20):
            raise DiskError(f"Not enough free disk space (needs {need // (1 << 20)} MB, "
                            f"{free // (1 << 20)} MB free)")

        if not it.segments:
            it.segments = plan_segments(it.total_size, it.resumable, self._target_connections())
        for seg in it.segments:
            seg.recv = seg.pos

        self._writer = FileWriter(it.part_path)
        await self._writer.open(it.total_size if it.total_size > 0 else 0)
        self.env.save(it, None)

    # ---- downloading ------------------------------------------------------
    async def _download(self) -> None:
        it = self.item
        self._cap = self._target_connections() if (it.resumable and it.total_size > 0) else 1
        try:
            while True:
                self._fill_slots()
                if not self._workers:
                    break
                done, _ = await asyncio.wait(set(self._workers), return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    self._workers.pop(task, None)
                    if task.cancelled():
                        continue
                    error = task.exception()
                    if error is not None:
                        raise error
                self._compact()
        finally:
            await self._cancel_workers()
        if any(not seg.done for seg in it.segments if seg.end is not None):
            raise FatalError("The download ended before all data was received")

    async def _cancel_workers(self) -> None:
        tasks = list(self._workers)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._workers.clear()

    def _fill_slots(self) -> None:
        loop = asyncio.get_running_loop()
        while len(self._workers) < self._cap:
            segment = self._next_segment()
            if segment is None:
                break
            task = loop.create_task(self._run_segment(segment))
            self._workers[task] = segment

    def _next_segment(self) -> Segment | None:
        active = {id(s) for s in self._workers.values()}
        for seg in self.item.segments:
            if not seg.done and id(seg) not in active:
                return seg
        return self._split()

    def _split(self) -> Segment | None:
        """Give a free connection half of the biggest remaining segment."""
        it = self.item
        if not (it.resumable and it.total_size > 0):
            return None
        best, best_left = None, 0
        for seg in self._workers.values():
            if seg.end is None:
                continue
            left = seg.end - seg.recv
            if left > best_left:
                best, best_left = seg, left
        if best is None or best_left < MIN_SPLIT:
            return None
        mid = best.recv + best_left // 2
        fresh = Segment(mid, best.end, mid)
        best.end = mid
        it.segments.insert(it.segments.index(best) + 1, fresh)
        return fresh

    def _compact(self) -> None:
        """Merge neighbouring finished segments so the list stays short."""
        active = {id(s) for s in self._workers.values()}
        merged: list[Segment] = []
        for seg in self.item.segments:
            prev = merged[-1] if merged else None
            if (prev is not None and prev.done and seg.done and prev.end == seg.start
                    and id(prev) not in active and id(seg) not in active):
                prev.end = seg.end
                prev.pos = prev.recv = seg.end
            else:
                merged.append(seg)
        self.item.segments[:] = merged

    async def _run_segment(self, seg: Segment) -> None:
        attempts = 0
        while True:
            before = seg.pos
            try:
                await self._stream_segment(seg)
                return
            except Requeue:
                return
            except DownloadError as exc:
                if seg.pos - before >= 64 * 1024:
                    attempts = 0
                if not exc.retryable:
                    if self._try_fallback(exc):
                        continue
                    raise
                attempts += 1
                if 0 <= self._max_retries() < attempts:
                    raise
                if isinstance(exc, HttpStatusError) and exc.status in (429, 503) and len(self._workers) > 1:
                    # The server is limiting simultaneous connections: use fewer.
                    self._cap = max(1, min(self._cap, len(self._workers) - 1))
                    if len(self._workers) > self._cap:
                        await asyncio.sleep(0.2)
                        return
                await self._backoff(attempts, exc)

    def _try_fallback(self, exc: DownloadError) -> bool:
        """If the redirected address stopped working, retry from the original link once."""
        it = self.item
        if (isinstance(exc, HttpStatusError) and exc.status in (401, 403, 404, 410)
                and it.final_url and it.final_url != it.url and not self._fallback_used):
            self._fallback_used = True
            it.final_url = ""
            return True
        return False

    async def _backoff(self, attempts: int, exc: DownloadError) -> None:
        base = float(self.env.settings.retry_base_delay)
        delay = min(60.0, base * (2 ** (attempts - 1))) * random.uniform(0.8, 1.2)
        if isinstance(exc, HttpStatusError) and exc.retry_after:
            delay = max(delay, min(exc.retry_after, 120.0))
        self.retries += 1
        self.message = f"{exc} - retrying in {int(delay + 0.5)}s"
        try:
            await asyncio.sleep(delay)
        finally:
            self.message = ""

    def _slice_size(self) -> int:
        rates = [r for r in (self.limiter.rate, self.env.global_limiter.rate) if r > 0]
        if not rates:
            return 0
        return max(1024, min(65536, int(min(rates) / 8)))

    async def _stream_segment(self, seg: Segment) -> None:
        it = self.item
        if seg.done:
            return
        ranged = it.resumable
        if not ranged and seg.pos > 0:       # can't resume: start this stream over
            seg.pos = seg.recv = seg.start
        headers = dict(self._headers)
        if ranged:
            last = "" if seg.end is None else str(seg.end - 1)
            headers["Range"] = f"bytes={seg.pos}-{last}"
        response = await self._transport.open(it.final_url or it.url, headers)
        try:
            self._check_response(response, seg, ranged)
            await self._pump_body(response, seg)
        finally:
            await response.aclose()

    def _check_response(self, response, seg: Segment, ranged: bool) -> None:
        status = response.status
        if status == 206:
            cr = parse_content_range(response.headers.get("Content-Range"))
            if cr is not None and cr.start is not None and cr.start != seg.pos:
                raise ServerChangedError("The server returned the wrong part of the file")
        elif status == 200:
            partial = seg.pos > 0 or (seg.end is not None and self.item.total_size > 0
                                      and seg.end < self.item.total_size)
            if ranged and partial:
                raise ServerChangedError(
                    "The server ignored the range request, so the download can't continue")
        else:
            raise status_error(status, response.headers)

    async def _pump_body(self, response, seg: Segment) -> None:
        writer = self._writer
        buf = bytearray()

        async def flush() -> None:
            if not buf:
                return
            data = bytes(buf)
            buf.clear()
            await writer.write_at(seg.pos, data)
            seg.pos += len(data)

        try:
            async with contextlib.aclosing(response.iter_chunks()) as chunks:
                finished = False
                async for chunk in chunks:
                    step = self._slice_size()
                    pieces = (chunk,) if not step else [chunk[i:i + step] for i in range(0, len(chunk), step)]
                    for piece in pieces:
                        if step:
                            await throttle(len(piece), self.limiter, self.env.global_limiter)
                        if seg.end is not None:
                            room = seg.end - seg.recv         # re-read: a split may have shortened us
                            if room <= 0:
                                finished = True
                                break
                            if len(piece) > room:
                                piece = piece[:room]
                        buf += piece
                        seg.recv += len(piece)
                        self.meter.add(len(piece))
                    if len(buf) >= FLUSH_SIZE:
                        await flush()
                    if finished or (seg.end is not None and seg.recv >= seg.end):
                        break
            await flush()
        except BaseException:
            try:                                    # keep what we already received
                await asyncio.shield(flush())
            except BaseException:
                pass
            raise
        if seg.end is None:
            seg.end = seg.recv                      # unknown size: the stream end is the file end
            self.item.total_size = seg.recv
        elif seg.recv < seg.end:
            raise NetworkError("The connection was closed before the download finished")

    # ---- finishing --------------------------------------------------------
    def _on_verify(self, fraction: float) -> None:
        if self.stop_reason:
            raise _Abort()
        self.verify_progress = fraction

    def _move_into_place(self) -> str:
        it = self.item
        name = it.filename
        if not it.overwrite and os.path.exists(os.path.join(it.directory, name)):
            name = unique_name(it.directory, name, check_part=False)
        target = os.path.join(it.directory, name)
        try:
            os.replace(it.part_path, target)
        except OSError as exc:
            raise DiskError(f"Couldn't save the file: {exc.strerror or exc}") from exc
        if self.env.settings.set_file_time and it.last_modified:
            with contextlib.suppress(Exception):
                stamp = parsedate_to_datetime(it.last_modified).timestamp()
                os.utime(target, (stamp, stamp))
        return name

    async def _finalize(self) -> None:
        it = self.item
        if it.min_speed < 0 and it.avg_speed > 0:      # very short download: use the average
            it.min_speed = it.avg_speed
        it.max_speed = max(it.max_speed, it.min_speed)
        await self._drain_checkpoint()
        if self._writer is not None:
            await self._writer.sync()
            await self._writer.aclose()
            self._writer = None
        expected = it.options.expected_hash.strip().lower()
        if expected:
            algo = it.options.expected_hash_algo or guess_algorithm(expected)
            if algo:
                self._set_state(State.VERIFYING)
                try:
                    digest = await asyncio.to_thread(hash_file, it.part_path, algo, self._on_verify)
                except _Abort:
                    raise asyncio.CancelledError() from None
                it.hash_result = f"{algo}:{digest}"
                if digest.lower() != expected:
                    it.segments = []                 # a resume must download everything again
                    raise FatalError(f"Checksum mismatch ({algo.upper()}): the file may be corrupted "
                                     "or altered. Press Resume to download it again.")
        name = await asyncio.to_thread(self._move_into_place)
        it.filename = name
        it.error = ""
        it.completed_at = time.time()
        self.note = ""
        self._set_state(State.COMPLETED)

    async def _after_stop(self) -> None:
        await self._cancel_workers()
        await self._drain_checkpoint()
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await self._writer.sync()
        self.message = ""
        self._set_state(State.PAUSED)

    async def _after_failure(self, exc: DownloadError) -> None:
        await self._cancel_workers()
        await self._drain_checkpoint()
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await self._writer.sync()
        self.message = ""
        self.item.error = str(exc)
        self._set_state(State.FAILED)

    async def _close_resources(self) -> None:
        await self._cancel_workers()
        if self._writer is not None:
            with contextlib.suppress(Exception):
                await self._writer.aclose()
            self._writer = None
        if self._transport is not None:
            with contextlib.suppress(Exception):
                await self._transport.aclose()
            self._transport = None
