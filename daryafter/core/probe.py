"""Ask the server about a link before downloading: size, resume support, file name."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping

from .errors import HttpStatusError
from .filenames import resolve_filename
from .models import ProbeResult
from .transport import Transport


@dataclass(slots=True)
class ContentRange:
    start: int | None
    end: int | None
    total: int | None


def parse_content_range(value: str | None) -> ContentRange | None:
    if not value:
        return None
    match = re.match(r"^\s*bytes\s+(?:(\d+)-(\d+)|\*)/(\d+|\*)\s*$", value, re.I)
    if not match:
        return None
    start, end, total = match.groups()
    return ContentRange(
        int(start) if start is not None else None,
        int(end) if end is not None else None,
        int(total) if total and total != "*" else None,
    )


def parse_retry_after(value: str | None) -> float | None:
    if value and value.strip().isdigit():
        return float(value.strip())
    return None


def status_error(status: int, headers) -> HttpStatusError:
    return HttpStatusError(status, "", parse_retry_after(headers.get("Retry-After")))


async def probe_url(transport: Transport, url: str, headers: Mapping[str, str]) -> ProbeResult:
    """Request the first byte only. A 206 answer means the server supports resuming."""
    request_headers = dict(headers)
    request_headers["Range"] = "bytes=0-0"
    response = await transport.open(url, request_headers)
    try:
        status = response.status
        h = response.headers
        total = -1
        resumable = False
        if status == 206:
            cr = parse_content_range(h.get("Content-Range"))
            resumable = True
            total = cr.total if cr and cr.total is not None else -1
        elif status == 200:
            length = h.get("Content-Length")
            total = int(length) if length and length.isdigit() else -1
        elif status == 416:
            cr = parse_content_range(h.get("Content-Range"))
            total = cr.total if cr and cr.total is not None else 0
        else:
            raise status_error(status, h)
        ctype = (h.get("Content-Type") or "").strip()
        final_url = response.url or url
        name = resolve_filename(url, final_url, h.get("Content-Disposition"), ctype)
        return ProbeResult(
            url=url, final_url=final_url, status=status, total_size=total, resumable=resumable,
            filename=name, content_type=ctype, etag=(h.get("ETag") or "").strip(),
            last_modified=(h.get("Last-Modified") or "").strip(),
            is_html="text/html" in ctype.lower(),
        )
    finally:
        await response.aclose()
