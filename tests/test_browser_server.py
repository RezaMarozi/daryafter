"""Tests for the browser-extension bridge (core/browser_server.py).

The server is plain standard library, so these tests need no Qt.
"""
import http.client
import json
import threading
import unittest

from daryafter.core.browser_server import CLIENT_HEADER, BrowserServer


def post(conn, path, body, headers=None, method="POST"):
    payload = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    conn.request(method, path, payload, headers or {})
    response = conn.getresponse()
    data = response.read()
    return response, (json.loads(data) if data else None)


class BrowserServerTestCase(unittest.TestCase):
    def setUp(self):
        self.added = []
        self.lock = threading.Lock()
        self.server = BrowserServer(
            lambda url, referrer, filename: self.added.append((url, referrer, filename)),
            port=0)                                  # ephemeral port, never 27240
        self.assertTrue(self.server.start())
        self.port = self.server.port

    def tearDown(self):
        self.server.stop()

    def connect(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        self.addCleanup(conn.close)
        return conn

    def headers(self, extra=None):
        base = {CLIENT_HEADER: "daryafter-extension/1", "Content-Type": "application/json"}
        base.update(extra or {})
        return base

    def test_ping(self):
        conn = self.connect()
        conn.request("GET", "/ping")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)
        data = json.loads(response.read())
        self.assertTrue(data["ok"])
        self.assertEqual(data["protocol"], 1)

    def test_add_ok(self):
        conn = self.connect()
        response, data = post(conn, "/add", {"url": "https://example.com/file.zip",
                                             "referrer": "https://example.com/",
                                             "filename": "file.zip"}, self.headers())
        self.assertEqual(response.status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(self.added, [("https://example.com/file.zip",
                                       "https://example.com/", "file.zip")])

    def test_add_missing_header_refused(self):
        conn = self.connect()
        response, _data = post(conn, "/add", {"url": "https://example.com/f.zip"})
        self.assertEqual(response.status, 403)
        self.assertEqual(self.added, [])

    def test_webpage_origin_refused(self):
        conn = self.connect()
        response, _data = post(conn, "/add", {"url": "https://example.com/f.zip"},
                               self.headers({"Origin": "https://evil.example"}))
        self.assertEqual(response.status, 403)
        self.assertEqual(self.added, [])

    def test_extension_origin_accepted(self):
        conn = self.connect()
        response, data = post(conn, "/add", {"url": "https://example.com/f.zip"},
                              self.headers({"Origin": "moz-extension://abcd-1234"}))
        self.assertEqual(response.status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"),
                         "moz-extension://abcd-1234")

    def test_bad_url_scheme_refused(self):
        conn = self.connect()
        for url in ("ftp://host/f.zip", "javascript:alert(1)", "/etc/passwd", ""):
            response, _data = post(conn, "/add", {"url": url}, self.headers())
            self.assertEqual(response.status, 400, url)
        self.assertEqual(self.added, [])

    def test_bad_referrer_refused(self):
        conn = self.connect()
        response, _data = post(conn, "/add", {"url": "https://example.com/f.zip",
                                              "referrer": "javascript:alert(1)"},
                               self.headers())
        self.assertEqual(response.status, 400)
        self.assertEqual(self.added, [])

    def test_body_too_large_refused(self):
        conn = self.connect()
        big = b'{"url": "' + b"a" * 200_000 + b'"}'
        conn.request("POST", "/add", big, self.headers())
        response = conn.getresponse()
        self.assertEqual(response.status, 413)
        self.assertEqual(self.added, [])

    def test_invalid_json_refused(self):
        conn = self.connect()
        conn.request("POST", "/add", b"not json", self.headers())
        response = conn.getresponse()
        self.assertEqual(response.status, 400)
        self.assertEqual(self.added, [])

    def test_unknown_path(self):
        conn = self.connect()
        response, _data = post(conn, "/other", {}, self.headers())
        self.assertEqual(response.status, 404)
        self.assertEqual(self.added, [])

    def test_preflight_for_extension_origin(self):
        conn = self.connect()
        conn.request("OPTIONS", "/add", b"", {"Origin": "chrome-extension://abc"})
        response = conn.getresponse()
        self.assertEqual(response.status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"),
                         "chrome-extension://abc")

    def test_preflight_for_webpage_origin_refused(self):
        conn = self.connect()
        conn.request("OPTIONS", "/add", b"", {"Origin": "https://evil.example"})
        response = conn.getresponse()
        self.assertEqual(response.status, 403)

    def test_busy_port_fails_cleanly(self):
        second = BrowserServer(lambda *args: None, port=self.port)
        self.assertFalse(second.start())
        self.assertEqual(second.port, self.port)

    def test_restart_after_stop(self):
        port = self.port
        self.server.stop()
        self.server._port = port
        self.assertTrue(self.server.start())
        conn = self.connect()
        conn.request("GET", "/ping")
        response = conn.getresponse()
        self.assertEqual(response.status, 200)


if __name__ == "__main__":
    unittest.main()
