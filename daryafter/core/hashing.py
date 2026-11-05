"""Checksum helpers."""
from __future__ import annotations

import hashlib
from typing import Callable

ALGORITHMS = ("md5", "sha1", "sha256", "sha512")


def hash_file(path: str, algo: str, progress: Callable[[float], None] | None = None,
              block: int = 1 << 20) -> str:
    import os

    h = hashlib.new(algo)
    size = os.path.getsize(path) or 1
    done = 0
    with open(path, "rb") as fh:
        while chunk := fh.read(block):
            h.update(chunk)
            done += len(chunk)
            if progress:
                progress(done / size)
    return h.hexdigest()


def guess_algorithm(digest: str) -> str:
    """Guess the algorithm from the length of a hex digest."""
    return {32: "md5", 40: "sha1", 64: "sha256", 128: "sha512"}.get(len(digest.strip()), "")
