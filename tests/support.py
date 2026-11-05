"""Test helpers: a local HTTP server with many behaviours and a stdlib-based transport."""
from __future__ import annotations

import asyncio
import http.client
import random
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from daryafter.core.errors import NetworkError

MiB = 1 << 20


def blob(seed: int, size: int) -> bytes:
    return random.Random(seed).randbytes(size)


DATA = {
    "/file.bin": blob(1, 6 * MiB),
    "/slow.bin": blob(2, 4 * MiB),
    "/norange.bin": blob(3, 3 * MiB),
    "/unknown.bin": blob(4, 2 * MiB),
    "/flaky.bin": blob(5, 6 * MiB),
    "/limit.bin": blob(6, 6 * MiB),
    "/cd.bin": blob(7, 100_000),
    "/changing.bin": blob(8, 4 * MiB),
    "/changing2.bin": blob(9, 4 * MiB),
    "/tiny.bin": b"hello",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        srv = self.server
        path = self.path.split("?")[0]
        rng = self.headers.get("Range")
        with srv.lock:
            srv.log.append((path, rng))
            srv.active += 1
            srv.max_active = max(srv.max_active, srv.active)
            active_now = srv.active
        try:
            self._serve(path, rng, active_now)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        finally:
            with srv.lock:
                srv.active -= 1

    def _serve(self, path, rng, active_now):
        srv = self.server
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file.bin")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/gone":
            self.send_response(410)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path == "/limit.bin" and active_now > 2:
            self.send_response(503)
            self.send_header("Retry-After", "0")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        key = "/changing.bin" if path == "/changing.bin" and srv.version == 1 else path
        if path == "/changing.bin" and srv.version == 2:
            key = "/changing2.bin"
        data = DATA.get(key)
        if data is None:
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        total = len(data)
        pace = 0.02 if path in ("/slow.bin", "/changing.bin") else 0.0
        extra = {}
        if path == "/cd.bin":
            extra["Content-Disposition"] = "attachment; filename*=UTF-8''%D9%81%D8%A7%DB%8C%D9%84%20test.bin"
        if path == "/changing.bin":
            extra["ETag"] = f'"v{srv.version}"'
        if path == "/unknown.bin":
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for i in range(0, total, 65536):
                piece = data[i:i + 65536]
                self.wfile.write(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
            self.wfile.write(b"0\r\n\r\n")
            return
        start, end, status = 0, total - 1, 200
        if rng and path != "/norange.bin":
            spec = rng.replace("bytes=", "")
            s, _, e = spec.partition("-")
            start = int(s)
            end = int(e) if e else total - 1
            end = min(end, total - 1)
            if start >= total:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            status = 206
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(end - start + 1))
        if path != "/norange.bin":
            self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
        for k, v in extra.items():
            self.send_header(k, v)
        self.end_headers()
        drop_after = None
        if path == "/flaky.bin" and status == 206 and end - start > 100_000:
            with srv.lock:
                if srv.drops_left > 0:
                    srv.drops_left -= 1
                    drop_after = 150_000
        sent = 0
        pos = start
        while pos <= end:
            piece = data[pos:min(end + 1, pos + 65536)]
            self.wfile.write(piece)
            pos += len(piece)
            sent += len(piece)
            if drop_after is not None and sent >= drop_after:
                self.connection.close()
                return
            if pace:
                time.sleep(pace)


class TestServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.lock = threading.Lock()
        self.log: list[tuple[str, str | None]] = []
        self.active = 0
        self.max_active = 0
        self.drops_left = 0
        self.version = 1
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self):
        self._thread.start()
        return self

    def stop(self):
        self.shutdown()
        self.server_close()

    def requests_for(self, path):
        return [r for p, r in self.log if p == path]


class StdlibResponse:
    def __init__(self, resp, status, headers, url):
        self._resp, self.status, self.headers, self.url = resp, status, headers, url

    async def iter_chunks(self):
        try:
            while True:
                chunk = await asyncio.to_thread(self._resp.read1, 65536)
                if not chunk:
                    return
                yield chunk
        except (OSError, http.client.HTTPException) as exc:
            raise NetworkError(f"read failed: {exc}") from exc

    async def aclose(self):
        await asyncio.to_thread(self._resp.close)


class StdlibTransport:
    async def open(self, url, headers):
        def do():
            request = urllib.request.Request(url, headers=dict(headers))
            try:
                r = urllib.request.urlopen(request, timeout=10)
                return StdlibResponse(r, r.status, r.headers, r.geturl())
            except urllib.error.HTTPError as exc:
                return StdlibResponse(exc, exc.code, exc.headers, url)
            except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
                raise NetworkError(f"connect failed: {exc}") from exc
        return await asyncio.to_thread(do)

    async def aclose(self):
        return None
