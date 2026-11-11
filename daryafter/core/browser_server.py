"""Small localhost bridge that the Daryafter browser extension talks to.

The extension (``extension/`` in this repository) sends download links
here as a plain HTTP POST. The server listens only on ``127.0.0.1`` and
refuses anything that a web page could forge:

- a custom header (``X-Daryafter-Client``) is required; browsers do not
  let a page send custom headers without a CORS pre-flight, and this
  server only approves the pre-flight for browser-extension origins, so
  a hostile page cannot make your browser POST here on its behalf;
- requests whose ``Origin`` is an ordinary web page (http/https) are
  refused outright;
- only ``http``/``https`` links are accepted and the body is limited to
  64 KiB.

The server is Qt-free (plain standard library) so it can be unit-tested
without a display; the caller decides how to hop over to the GUI thread.
"""
from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from ..branding import APP_NAME, VERSION

DEFAULT_PORT = 27240
MAX_BODY_BYTES = 65536
CLIENT_HEADER = "X-Daryafter-Client"
PROTOCOL_VERSION = 1

log = logging.getLogger(__name__)


def is_http_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def _origin_scheme(origin: str) -> str:
    try:
        return urlsplit(origin).scheme.lower()
    except ValueError:
        return ""


def _origin_is_webpage(origin: str) -> bool:
    return _origin_scheme(origin) in ("http", "https")


def _origin_is_extension(origin: str) -> bool:
    return _origin_scheme(origin) in ("moz-extension", "chrome-extension", "safari-web-extension",
                                      "extension", "edge-extension")


class _Handler(BaseHTTPRequestHandler):
    server_version = f"DaryafterBridge/{VERSION}"
    protocol_version = "HTTP/1.1"
    on_add = None                              # class attribute: set by BrowserServer

    # ---- replies ---------------------------------------------------------
    def _reply(self, code: int, payload: dict, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _bad(self, code: int, error: str) -> None:
        self._reply(code, {"ok": False, "error": error})

    # ---- verbs -----------------------------------------------------------
    def do_HEAD(self) -> None:
        self._reply(200, {"ok": True, "app": APP_NAME, "version": VERSION,
                          "protocol": PROTOCOL_VERSION})

    def do_GET(self) -> None:
        if self.path.rstrip("/") in ("/ping", "/ping/"):
            self._reply(200, {"ok": True, "app": APP_NAME, "version": VERSION,
                              "protocol": PROTOCOL_VERSION})
        else:
            self._bad(404, "unknown path")

    def do_OPTIONS(self) -> None:
        """CORS pre-flight. Only extension origins may pass."""
        origin = self.headers.get("Origin", "")
        if not _origin_is_extension(origin):
            self._bad(403, "preflight refused")
            return
        self._reply(204, {}, extra={
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": f"{CLIENT_HEADER}, Content-Type",
            "Vary": "Origin",
        })

    def do_POST(self) -> None:
        if self.path.rstrip("/") not in ("/add", "/add/"):
            self._bad(404, "unknown path")
            return
        origin = self.headers.get("Origin", "")
        if _origin_is_webpage(origin):
            log.info("browser bridge: refused request from web origin %s", origin)
            self._bad(403, "refused")
            return
        if self.headers.get(CLIENT_HEADER, "").strip() == "":
            self._bad(403, f"missing {CLIENT_HEADER} header")
            return
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if length < 0:
            self._bad(411, "Content-Length required")
            return
        if length > MAX_BODY_BYTES:
            self._bad(413, "body too large")
            return
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._bad(400, "body is not valid JSON")
            return
        if not isinstance(data, dict):
            self._bad(400, "body must be a JSON object")
            return
        url = str(data.get("url") or "").strip()
        referrer = str(data.get("referrer") or "").strip()
        filename = str(data.get("filename") or "").strip()
        if not is_http_url(url):
            self._bad(400, "url must be a full http:// or https:// link")
            return
        if referrer and not is_http_url(referrer):
            self._bad(400, "referrer must be a full http:// or https:// link")
            return
        log.info("browser bridge: adding %s", url)
        try:
            self.on_add(url, referrer, filename)
        except Exception:
            log.exception("browser bridge: the caller failed to handle a link")
            self._bad(500, "internal error")
            return
        extra = {}
        if _origin_is_extension(origin):
            extra = {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}
        self._reply(200, {"ok": True}, extra=extra)

    def log_message(self, format: str, *args) -> None:      # noqa: A002 (http.server API)
        log.debug("browser bridge: " + format, *args)


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address) -> None:
        """Connection resets and closed pipes are routine; keep them out of the log."""
        log.debug("browser bridge: connection from %s ended with an error", client_address)


class BrowserServer:
    """Runs the bridge on a background thread. ``on_add(url, referrer, filename)``
    is called from the server thread; hop to the GUI thread yourself."""

    def __init__(self, on_add, port: int = DEFAULT_PORT):
        self._on_add = on_add
        self._port = port
        self._httpd: ThreadingHTTPServer | None = None

    @property
    def port(self) -> int:
        if self._httpd is not None:
            return self._httpd.server_address[1]
        return self._port

    def start(self) -> bool:
        """Bind and serve. Returns False when the port is busy."""
        if self._httpd is not None:
            return True
        handler = type("_BoundHandler", (_Handler,), {"on_add": staticmethod(self._on_add)})
        try:
            self._httpd = _QuietServer(("127.0.0.1", self._port), handler)
        except OSError as exc:
            log.warning("browser bridge: could not listen on 127.0.0.1:%s (%s); "
                        "the browser extension will see Daryafter as offline", self._port, exc)
            return False
        self._httpd.daemon_threads = True
        thread = threading.Thread(target=self._httpd.serve_forever,
                                  name="daryafter-browser-bridge", daemon=True)
        thread.start()
        log.info("browser bridge listening on http://127.0.0.1:%s", self.port)
        return True

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        log.info("browser bridge stopped")
