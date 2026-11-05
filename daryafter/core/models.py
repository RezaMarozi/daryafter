"""Data models shared by the engine, storage and the UI."""
from __future__ import annotations

import enum
import os
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any
from urllib.parse import urlsplit


class State(enum.StrEnum):
    QUEUED = "queued"
    CONNECTING = "connecting"
    DOWNLOADING = "downloading"
    PAUSED = "paused"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"


RUNNING_STATES = frozenset({State.CONNECTING, State.DOWNLOADING, State.VERIFYING})
FINAL_STATES = frozenset({State.COMPLETED, State.FAILED})


def _from_dict(cls, data: dict[str, Any]):
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


@dataclass(slots=True, eq=False)
class Segment:
    """A byte range [start, end) of the file. ``pos`` is the next byte that
    has not been written to disk yet; ``recv`` also counts bytes still buffered."""

    start: int
    end: int | None          # None = unknown size (read until the stream ends)
    pos: int
    recv: int = 0

    def __post_init__(self) -> None:
        if self.recv < self.pos:
            self.recv = self.pos

    @property
    def done(self) -> bool:
        return self.end is not None and self.pos >= self.end

    def to_list(self) -> list:
        return [self.start, self.end, self.pos]


@dataclass
class DownloadOptions:
    connections: int = 8
    max_speed: bool = False          # use as many connections as possible, no per-file limit
    speed_limit: int = 0             # bytes/second, 0 = unlimited
    referer: str = ""
    user_agent: str = ""             # empty = use the global default
    cookies: str = ""
    username: str = ""
    password: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    expected_hash_algo: str = ""     # md5 | sha1 | sha256 | sha512
    expected_hash: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadOptions":
        return _from_dict(cls, data)


@dataclass
class DownloadItem:
    id: int = 0
    url: str = ""
    final_url: str = ""
    filename: str = ""
    directory: str = ""
    category: str = "Other"
    total_size: int = -1
    resumable: bool = False
    state: State = State.QUEUED
    error: str = ""
    etag: str = ""
    last_modified: str = ""
    content_type: str = ""
    priority: int = 0
    overwrite: bool = False
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    options: DownloadOptions = field(default_factory=DownloadOptions)
    segments: list[Segment] = field(default_factory=list)
    active_seconds: float = 0.0
    session_bytes: int = 0
    min_speed: float = -1.0          # -1 = not measured yet
    max_speed: float = 0.0
    hash_result: str = ""

    # ---- derived values -------------------------------------------------
    @property
    def part_path(self) -> str:
        return os.path.join(self.directory, self.filename + ".part")

    @property
    def final_path(self) -> str:
        return os.path.join(self.directory, self.filename)

    @property
    def downloaded(self) -> int:
        """Bytes safely written to disk."""
        return sum(max(0, s.pos - s.start) for s in self.segments)

    @property
    def received(self) -> int:
        """Bytes received so far, including data still in memory."""
        return sum(max(0, max(s.recv, s.pos) - s.start) for s in self.segments)

    @property
    def avg_speed(self) -> float:
        return self.session_bytes / self.active_seconds if self.active_seconds > 0.5 else 0.0

    @property
    def host(self) -> str:
        return urlsplit(self.url).hostname or ""

    # ---- (de)serialisation ---------------------------------------------
    def to_dict(self, segments: list[list] | None = None) -> dict[str, Any]:
        data = {f.name: getattr(self, f.name) for f in fields(self)
                if f.name not in ("options", "segments")}
        data["state"] = str(self.state)
        data["options"] = asdict(self.options)
        data["segments"] = segments if segments is not None else [s.to_list() for s in self.segments]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DownloadItem":
        data = dict(data)
        options = DownloadOptions.from_dict(data.pop("options", {}) or {})
        segments = [Segment(int(s[0]), None if s[1] is None else int(s[1]), int(s[2]))
                    for s in data.pop("segments", []) or []]
        data["state"] = State(data.get("state", "paused"))
        item = _from_dict(cls, data)
        item.options = options
        item.segments = segments
        return item


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Immutable copy of an item's state, safe to hand to another thread."""

    id: int
    url: str
    host: str
    filename: str
    directory: str
    final_path: str
    category: str
    state: State
    total: int
    downloaded: int
    speed: float
    eta: float | None
    error: str
    message: str
    resumable: bool
    connections: int
    segments: tuple[tuple[int, int, int], ...]     # (start, end, received)
    created_at: float
    completed_at: float
    priority: int
    avg_speed: float
    min_speed: float
    max_speed: float
    active_seconds: float
    hash_result: str
    verify_progress: float

    @property
    def progress(self) -> float:
        if self.state == State.COMPLETED:
            return 1.0
        if self.total > 0:
            return min(1.0, self.downloaded / self.total)
        return 0.0


def make_snapshot(item: DownloadItem, speed: float = 0.0, eta: float | None = None,
                  message: str = "", connections: int = 0, verify_progress: float = 0.0) -> Snapshot:
    segs = tuple(
        (s.start, s.end if s.end is not None else max(s.recv, s.pos), max(s.recv, s.pos))
        for s in item.segments
    )
    if item.state == State.COMPLETED:
        downloaded = item.total_size if item.total_size > 0 else item.downloaded
    else:
        downloaded = item.received
    return Snapshot(
        id=item.id, url=item.url, host=item.host, filename=item.filename,
        directory=item.directory, final_path=item.final_path, category=item.category,
        state=item.state, total=item.total_size, downloaded=downloaded, speed=speed, eta=eta,
        error=item.error, message=message, resumable=item.resumable, connections=connections,
        segments=segs, created_at=item.created_at, completed_at=item.completed_at,
        priority=item.priority, avg_speed=item.avg_speed, min_speed=max(0.0, item.min_speed),
        max_speed=item.max_speed, active_seconds=item.active_seconds,
        hash_result=item.hash_result, verify_progress=verify_progress,
    )


@dataclass(slots=True)
class ProbeResult:
    url: str
    final_url: str
    status: int
    total_size: int            # -1 = unknown
    resumable: bool
    filename: str
    content_type: str = ""
    etag: str = ""
    last_modified: str = ""
    is_html: bool = False


@dataclass(slots=True)
class AddRequest:
    url: str
    filename: str = ""
    directory: str = ""                  # "" = default download folder
    use_category_folder: bool = True
    options: DownloadOptions = field(default_factory=DownloadOptions)
    start_now: bool = True
    overwrite: bool = False
    probe: ProbeResult | None = None


@dataclass(slots=True)
class Event:
    """Message from the engine to the UI. ``kind`` is one of:
    added, updated, removed, progress, completed, notice, offline, schedule."""

    kind: str
    snapshot: Snapshot | None = None
    snapshots: list[Snapshot] = field(default_factory=list)
    item_id: int = 0
    text: str = ""
    speed: float = 0.0
    flag: bool = False
