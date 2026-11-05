"""Exception types used by the download engine."""
from __future__ import annotations

RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504, 520, 521, 522, 523, 524})

_HINTS = {
    401: "Sign-in required",
    403: "Access denied (the link may have expired)",
    404: "File not found on the server",
    410: "The link is no longer available",
    416: "The server rejected the requested range",
    429: "Too many requests",
    503: "Server temporarily unavailable",
}


def describe_status(status: int, reason: str = "") -> str:
    base = _HINTS.get(status) or reason or "Server error"
    return f"{base} (HTTP {status})"


class DownloadError(Exception):
    """Base class. ``retryable`` says whether trying again can help."""

    retryable = False


class NetworkError(DownloadError):
    retryable = True


class HttpStatusError(DownloadError):
    def __init__(self, status: int, reason: str = "", retry_after: float | None = None):
        self.status = status
        self.reason = reason
        self.retry_after = retry_after
        self.retryable = status in RETRYABLE_STATUS
        super().__init__(describe_status(status, reason))


class DiskError(DownloadError):
    pass


class ServerChangedError(DownloadError):
    pass


class FatalError(DownloadError):
    pass


class Requeue(Exception):
    """Internal: a worker gives its slot back; the segment is retried later."""
