"""Owns all downloads: queue, persistence, events and offline mode.

Everything here runs on the engine's asyncio thread. The UI talks to it through
``EngineService`` (service.py)."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import fields
from datetime import datetime
from typing import Callable
from urllib.parse import urlsplit

from .categories import category_for
from .errors import FatalError
from .filenames import filename_from_url, sanitize_filename, unique_name
from .job import DownloadJob, JobEnv, build_headers
from .limiter import RateLimiter
from .models import (RUNNING_STATES, AddRequest, DownloadItem, DownloadOptions, Event,
                     ProbeResult, Snapshot, State, make_snapshot)
from .power import set_keep_awake
from .probe import probe_url
from .schedule import Rule, Scheduler, rules_from_settings
from .settings import Settings
from .storage import Storage
from .transport import Transport

log = logging.getLogger(__name__)

TransportFactory = Callable[[DownloadOptions], Transport]


class DownloadManager:
    def __init__(self, storage: Storage, settings: Settings, emit: Callable[[Event], None],
                 transport_factory: TransportFactory | None = None,
                 now: Callable[[], datetime] = datetime.now):
        self.storage = storage
        self.scheduler = Scheduler(now)
        self._rule_tasks: set[asyncio.Task] = set()
        self.settings = settings
        self._emit_cb = emit
        self._transport_factory = transport_factory
        self.items: dict[int, DownloadItem] = {}
        self.jobs: dict[int, DownloadJob] = {}
        self.offline = False
        self.global_limiter = RateLimiter(settings.global_speed_limit)
        self._offline_paused: set[int] = set()
        self._ticker: asyncio.Task | None = None
        self._closing = False
        self._had_active = False
        self._awake = False

    # ------------------------------------------------------------------ plumbing
    def _emit(self, kind: str, **kwargs) -> None:
        try:
            self._emit_cb(Event(kind, **kwargs))
        except Exception:
            log.exception("event listener failed")

    def _make_transport(self, options: DownloadOptions) -> Transport:
        if self._transport_factory is not None:
            return self._transport_factory(options)
        from .transport import make_httpx_transport

        return make_httpx_transport(self.settings.network_config(), options.username,
                                    options.password, max_connections=32)

    def _env(self) -> JobEnv:
        return JobEnv(settings=self.settings, global_limiter=self.global_limiter,
                      make_transport=self._make_transport, save=self._save_progress,
                      changed=self._on_job_state)

    def _save_progress(self, item: DownloadItem, segments: list | None) -> None:
        if item.id in self.items:
            self.storage.save_item(item, segments)

    def _on_job_state(self, item: DownloadItem) -> None:
        if item.id not in self.items:
            return
        self.storage.save_item(item)
        self._emit("updated", snapshot=self._snapshot(item))

    def _snapshot(self, item: DownloadItem) -> Snapshot:
        job = self.jobs.get(item.id)
        if job is not None and job.active:
            return job.snapshot()
        return make_snapshot(item)

    def snapshots(self) -> list[Snapshot]:
        return [self._snapshot(i) for i in sorted(self.items.values(), key=lambda i: i.id)]

    async def a_snapshots(self) -> list[Snapshot]:
        return self.snapshots()

    # ------------------------------------------------------------------ lifecycle
    async def startup(self) -> None:
        for item in self.storage.load_items():
            if item.state in RUNNING_STATES or item.state == State.QUEUED:
                item.state = State.QUEUED if self.settings.resume_on_start else State.PAUSED
            self.items[item.id] = item
        self._ticker = asyncio.get_running_loop().create_task(self._tick_loop())
        self._pump()

    async def shutdown(self) -> None:
        self._closing = True
        if self._ticker is not None:
            self._ticker.cancel()
        await asyncio.gather(*(j.stop("shutdown") for j in list(self.jobs.values())),
                             return_exceptions=True)
        for item in self.items.values():
            if item.state in RUNNING_STATES or item.state == State.QUEUED:
                item.state = State.PAUSED
            self.storage.save_item(item)
        if self.settings.clear_history_on_exit and self.storage.persistent:
            for item in self.items.values():          # failed downloads would leave orphan .part files
                if item.state == State.FAILED:
                    with contextlib.suppress(OSError):
                        os.remove(item.part_path)
            self.storage.clear_finished()
            self.storage.scrub()
        set_keep_awake(False)

    def apply_settings(self, new: Settings) -> None:
        for f in fields(Settings):
            setattr(self.settings, f.name, getattr(new, f.name))
        self.global_limiter.set_rate(self.settings.global_speed_limit)
        want = bool(self.settings.remember_passwords) and self.storage.persistent
        if want != self.storage.store_passwords:
            self.storage.store_passwords = want
            if not want:                              # switched off: erase passwords already on disk
                for item in self.items.values():
                    self.storage.save_item(item)
                self.storage.scrub()
        self._pump()

    # ------------------------------------------------------------------ queue
    def _pump(self) -> None:
        if not self.offline and not self._closing:
            running = sum(1 for j in self.jobs.values() if j.active)
            limit = max(1, int(self.settings.max_concurrent))
            waiting = sorted((i for i in self.items.values()
                              if i.state == State.QUEUED and i.id not in self.jobs),
                             key=lambda i: (-i.priority, i.id))
            for item in waiting:
                if running >= limit:
                    break
                self._start_job(item)
                running += 1
        self._update_awake()

    def _start_job(self, item: DownloadItem) -> None:
        job = DownloadJob(item, self._env())
        self.jobs[item.id] = job
        task = job.start()
        task.add_done_callback(lambda _t, j=job: self._job_finished(j))

    def _job_finished(self, job: DownloadJob) -> None:
        item = job.item
        if self.jobs.get(item.id) is job:
            del self.jobs[item.id]
        if item.id not in self.items:
            return
        if item.state in RUNNING_STATES or item.state == State.QUEUED:
            item.state = State.PAUSED            # cancelled before it could report
            self.storage.save_item(item)
        snapshot = make_snapshot(item)
        self._emit("updated", snapshot=snapshot)
        if item.state == State.COMPLETED:
            self._emit("completed", snapshot=snapshot)
        if not self._closing:
            self._pump()

    def _update_awake(self) -> None:
        want = bool(self.settings.prevent_sleep and any(j.active for j in self.jobs.values()))
        if want != self._awake:
            self._awake = want
            set_keep_awake(want)

    async def _tick_loop(self) -> None:
        while True:
            await asyncio.sleep(0.5)
            try:
                self._tick()
            except Exception:
                log.exception("tick failed")

    # ------------------------------------------------------------------ timers
    def _check_schedule(self) -> None:
        rules = rules_from_settings(self.settings)
        for rule in self.scheduler.due(rules):
            task = asyncio.get_running_loop().create_task(self._run_rule(rule))
            self._rule_tasks.add(task)
            task.add_done_callback(self._rule_tasks.discard)

    async def _run_rule(self, rule: Rule) -> None:
        try:
            if rule.action == "start":
                await self.set_offline(False)
                await self.resume_all()
            elif rule.action == "stop":
                await self.pause_all()
            elif rule.action == "disconnect":
                await self.set_offline(True)
            if rule.once and 0 <= rule.index < len(self.settings.schedule):
                self.settings.schedule[rule.index]["enabled"] = False     # the window saves the settings
        except Exception:
            log.exception("timer failed")
        self._emit("schedule", text=rule.action, flag=rule.once)

    def _tick(self) -> None:
        self._check_schedule()
        now = time.monotonic()
        snapshots: list[Snapshot] = []
        total = 0.0
        for job in list(self.jobs.values()):
            if job.active:
                job.tick(now)
                snap = job.snapshot()
                snapshots.append(snap)
                total += snap.speed
        if snapshots or self._had_active:
            self._emit("progress", snapshots=snapshots, speed=total)
        self._had_active = bool(snapshots)

    # ------------------------------------------------------------------ links
    @staticmethod
    def _validate_url(url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise FatalError("Enter a full link that starts with http:// or https://")

    async def probe(self, url: str, options: DownloadOptions | None = None) -> ProbeResult:
        url = url.strip()
        self._validate_url(url)
        if self.offline:
            raise FatalError("Offline mode is on. Turn it off to check links.")
        options = options or DownloadOptions()
        transport = self._make_transport(options)
        try:
            return await probe_url(transport, url, build_headers(options, self.settings))
        finally:
            await transport.aclose()

    def _reserved(self, path: str) -> bool:
        key = os.path.normcase(path)
        return any(os.path.normcase(i.final_path) == key
                   for i in self.items.values() if i.state != State.COMPLETED)

    async def add(self, request: AddRequest) -> int:
        url = request.url.strip()
        self._validate_url(url)
        probe = request.probe
        name = sanitize_filename(request.filename or (probe.filename if probe else "")
                                 or filename_from_url(url))
        base = request.directory or self.settings.resolved_download_dir()
        category = category_for(name)
        directory = os.path.join(base, category) if (request.use_category_folder
                                                      and category != "Other") else base
        if not request.overwrite:
            name = unique_name(directory, name, taken=self._reserved)
        item = DownloadItem(url=url, filename=name, directory=directory, category=category,
                            options=request.options, overwrite=request.overwrite,
                            state=State.QUEUED if request.start_now else State.PAUSED)
        if probe is not None:
            item.final_url, item.total_size = probe.final_url, probe.total_size
            item.resumable, item.etag = probe.resumable, probe.etag
            item.last_modified, item.content_type = probe.last_modified, probe.content_type
        self.storage.insert_item(item)
        self.items[item.id] = item
        self._emit("added", snapshot=make_snapshot(item))
        if request.start_now:
            self._pump()
        return item.id

    # ------------------------------------------------------------------ actions
    async def pause(self, item_id: int, reason: str = "pause") -> None:
        item = self.items.get(item_id)
        if item is None:
            return
        job = self.jobs.get(item_id)
        if job is not None and job.active:
            await job.stop(reason)
        elif item.state == State.QUEUED:
            item.state = State.PAUSED
            self.storage.save_item(item)
            self._emit("updated", snapshot=make_snapshot(item))

    async def resume(self, item_id: int) -> None:
        item = self.items.get(item_id)
        if item is not None and item.state in (State.PAUSED, State.FAILED):
            item.state, item.error = State.QUEUED, ""
            self.storage.save_item(item)
            self._emit("updated", snapshot=make_snapshot(item))
            self._pump()

    async def pause_all(self) -> None:
        await asyncio.gather(*(self.pause(i) for i in list(self.items)), return_exceptions=True)

    async def resume_all(self) -> None:
        for item_id in list(self.items):
            await self.resume(item_id)

    async def restart(self, item_id: int) -> None:
        """Throw away progress and download from the beginning."""
        item = self.items.get(item_id)
        if item is None:
            return
        await self.pause(item_id)
        item.segments = []
        item.error = ""
        with contextlib.suppress(OSError):
            os.remove(item.part_path)
        item.state = State.PAUSED
        await self.resume(item_id)

    async def remove(self, item_id: int, delete_files: bool = False) -> None:
        item = self.items.get(item_id)
        if item is None:
            return
        job = self.jobs.get(item_id)
        if job is not None and job.active:
            await job.stop("remove")
        self.jobs.pop(item_id, None)
        self.items.pop(item_id, None)
        self.storage.delete_item(item_id)
        if item.state != State.COMPLETED:
            with contextlib.suppress(OSError):
                os.remove(item.part_path)
        elif delete_files:
            with contextlib.suppress(OSError):
                os.remove(item.final_path)
        self._emit("removed", item_id=item_id)
        self._pump()

    async def clear_completed(self) -> None:
        for item in [i for i in self.items.values() if i.state == State.COMPLETED]:
            await self.remove(item.id)

    async def clear_history(self) -> int:
        """Remove completed and failed downloads from the list and wipe them from the database.
        Downloaded files stay on disk; partial files of failed downloads are deleted."""
        ids = [i.id for i in self.items.values() if i.state in (State.COMPLETED, State.FAILED)]
        for item_id in ids:
            await self.remove(item_id)
        self.storage.scrub()
        return len(ids)

    async def rename(self, item_id: int, new_name: str) -> None:
        item = self.items.get(item_id)
        if item is None or item.state in RUNNING_STATES:
            return
        new_name = sanitize_filename(new_name)
        if new_name == item.filename:
            return
        if not item.overwrite or item.state == State.COMPLETED:
            new_name = unique_name(item.directory, new_name, taken=self._reserved)
        old_part, old_final = item.part_path, item.final_path
        with contextlib.suppress(OSError):
            if item.state == State.COMPLETED:
                os.replace(old_final, os.path.join(item.directory, new_name))
            elif os.path.exists(old_part):
                os.replace(old_part, os.path.join(item.directory, new_name + ".part"))
        item.filename = new_name
        item.category = category_for(new_name)
        self.storage.save_item(item)
        self._emit("updated", snapshot=make_snapshot(item))

    async def update_url(self, item_id: int, url: str) -> None:
        """'Refresh link': give an expired download a new address, then resume it."""
        item = self.items.get(item_id)
        url = url.strip()
        self._validate_url(url)
        if item is None or item.state in RUNNING_STATES:
            return
        item.url, item.final_url = url, ""
        if item.state == State.FAILED:
            item.state, item.error = State.PAUSED, ""
        self.storage.save_item(item)
        self._emit("updated", snapshot=make_snapshot(item))

    async def set_item_limit(self, item_id: int, bytes_per_second: int) -> None:
        item = self.items.get(item_id)
        if item is None:
            return
        item.options.speed_limit = max(0, int(bytes_per_second))
        job = self.jobs.get(item_id)
        if job is not None:
            job.limiter.set_rate(0 if item.options.max_speed else item.options.speed_limit)
        self.storage.save_item(item)

    async def set_priority(self, item_id: int, priority: int) -> None:
        item = self.items.get(item_id)
        if item is not None:
            item.priority = int(priority)
            self.storage.save_item(item)
            self._emit("updated", snapshot=self._snapshot(item))

    async def move_in_queue(self, item_id: int, where: str) -> None:
        """Change the place of a download in the queue: top | up | down | bottom.
        The queue is every unfinished download, ordered by priority and then by age."""
        order = sorted((i for i in self.items.values() if i.state != State.COMPLETED),
                       key=lambda i: (-i.priority, i.id))
        item = self.items.get(item_id)
        if item is None or item not in order:
            return
        old = order.index(item)
        new = {"top": 0, "up": max(0, old - 1), "down": min(len(order) - 1, old + 1),
               "bottom": len(order) - 1}.get(where, old)
        if new == old:
            return
        order.insert(new, order.pop(old))
        for pos, entry in enumerate(order):              # renumber so the order is explicit
            priority = len(order) - pos
            if entry.priority != priority:
                entry.priority = priority
                self.storage.save_item(entry)
                self._emit("updated", snapshot=self._snapshot(entry))
        self._pump()

    # ------------------------------------------------------------------ offline mode
    async def set_offline(self, offline: bool) -> None:
        """While offline the app opens no connections at all."""
        if offline == self.offline:
            return
        self.offline = offline
        if offline:
            running = [j.item.id for j in self.jobs.values() if j.active]
            self._offline_paused.update(running)
            await asyncio.gather(*(self.pause(i, "offline") for i in running), return_exceptions=True)
        else:
            for item_id in list(self._offline_paused):
                item = self.items.get(item_id)
                if item is not None and item.state == State.PAUSED:
                    item.state = State.QUEUED
                    self.storage.save_item(item)
                    self._emit("updated", snapshot=make_snapshot(item))
            self._offline_paused.clear()
            self._pump()
        self._emit("offline", flag=offline)

    # ------------------------------------------------------------------ private mode
    def discard_unfinished(self) -> int:
        """Delete partial files of unfinished downloads (used when leaving private mode)."""
        count = 0
        for item in self.items.values():
            if item.state != State.COMPLETED:
                with contextlib.suppress(OSError):
                    os.remove(item.part_path)
                    count += 1
        return count
