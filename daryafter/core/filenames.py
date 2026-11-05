"""File-name detection and cleaning (Windows-safe)."""
from __future__ import annotations

import mimetypes
import os
import re
from typing import Callable
from urllib.parse import parse_qs, unquote, urlsplit

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_BIDI = re.compile("[\u202a-\u202e\u2066-\u2069]")
_RESERVED = {"CON", "PRN", "AUX", "NUL",
             *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_NAME = 180

_EXT_OVERRIDES = {
    "text/plain": ".txt", "text/html": ".html", "image/jpeg": ".jpg", "application/zip": ".zip",
    "application/pdf": ".pdf", "video/mp4": ".mp4", "audio/mpeg": ".mp3", "image/png": ".png",
    "application/x-7z-compressed": ".7z", "application/vnd.rar": ".rar",
    "application/x-msdownload": ".exe", "application/gzip": ".gz",
}


def split_ext(name: str) -> tuple[str, str]:
    stem, ext = os.path.splitext(name)
    if stem.lower().endswith(".tar") and ext:
        return stem[:-4], ".tar" + ext
    return stem, ext


def sanitize_filename(name: str, default: str = "download") -> str:
    name = _BIDI.sub("", name or "")
    name = _ILLEGAL.sub("_", name).strip().rstrip(" .")
    if not name:
        return default
    stem, ext = split_ext(name)
    if stem.upper() in _RESERVED:
        name = "_" + stem + ext
        stem = "_" + stem
    if len(name) > MAX_NAME:
        ext = ext[:20]
        name = stem[: MAX_NAME - len(ext)] + ext
    return name


def _fix_text(value: str) -> str:
    """Repair names that were UTF-8 on the wire but decoded as Latin-1."""
    if re.search(r"%[0-9A-Fa-f]{2}", value):
        try:
            decoded = unquote(value, errors="strict")
            return decoded
        except UnicodeDecodeError:
            pass
    if any(0x80 <= ord(c) <= 0xFF for c in value) and all(ord(c) <= 0xFF for c in value):
        try:
            return value.encode("latin-1").decode("utf-8")
        except UnicodeError:
            pass
    return value


def parse_content_disposition(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"filename\*\s*=\s*([^;]+)", value, re.I)
    if match:
        raw = match.group(1).strip().strip('"')
        inner = re.match(r"^([\w\-]+)'[^']*'(.*)$", raw)
        if inner:
            charset, encoded = inner.groups()
            try:
                return unquote(encoded, encoding=charset, errors="replace")
            except LookupError:
                return unquote(encoded, errors="replace")
        return unquote(raw)
    match = re.search(r'filename\s*=\s*"((?:[^"\\]|\\.)*)"', value, re.I)
    if match:
        name = re.sub(r"\\(.)", r"\1", match.group(1))
    else:
        match = re.search(r"filename\s*=\s*([^;]+)", value, re.I)
        if not match:
            return None
        name = match.group(1).strip()
    return _fix_text(name) or None


def filename_from_url(url: str) -> str:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    # S3-style signed links carry the real name in a query parameter
    for key in ("response-content-disposition", "rscd"):
        if key in query:
            name = parse_content_disposition(query[key][0])
            if name:
                return name
    last = unquote(parts.path.rsplit("/", 1)[-1])
    if last:
        return last
    for key in ("filename", "file", "fname", "name"):
        if key in query and query[key][0]:
            return query[key][0]
    return ""


def extension_for(content_type: str) -> str:
    ctype = (content_type or "").split(";")[0].strip().lower()
    if not ctype or ctype in ("application/octet-stream", "binary/octet-stream"):
        return ""
    return _EXT_OVERRIDES.get(ctype) or mimetypes.guess_extension(ctype) or ""


def resolve_filename(url: str, final_url: str = "", content_disposition: str | None = None,
                     content_type: str = "") -> str:
    name = parse_content_disposition(content_disposition) or ""
    if not name and final_url:
        name = filename_from_url(final_url)
    if not name:
        name = filename_from_url(url)
    name = os.path.basename(name.replace("\\", "/"))
    if not name:
        name = "index.html" if "html" in (content_type or "") else "download"
    if not os.path.splitext(name)[1]:
        name += extension_for(content_type)
    return sanitize_filename(name)


def unique_name(directory: str, filename: str, taken: Callable[[str], bool] | None = None,
                check_part: bool = True) -> str:
    """Return ``filename`` or ``filename (1)`` etc. so it doesn't collide."""
    stem, ext = split_ext(filename)
    candidate = filename
    counter = 0
    while True:
        path = os.path.join(directory, candidate)
        if not (os.path.exists(path) or (check_part and os.path.exists(path + ".part"))
                or (taken and taken(path))):
            return candidate
        counter += 1
        candidate = f"{stem} ({counter}){ext}"
