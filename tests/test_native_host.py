"""Tests for the native messaging host used to auto-start Daryafter."""
import io
import json
import struct
import unittest
from unittest import mock

import importlib.util
from pathlib import Path

_HOST_PATH = Path(__file__).resolve().parent.parent / "extension" / "native-host" / "daryafter_native_host.py"
_spec = importlib.util.spec_from_file_location("daryafter_native_host", _HOST_PATH)
host = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(host)


def encode(message: dict) -> bytes:
    raw = json.dumps(message).encode("utf-8")
    return struct.pack("<I", len(raw)) + raw


class ReadWriteTestCase(unittest.TestCase):
    def test_roundtrip(self):
        buffer = io.BytesIO(encode({"cmd": "start"}))
        self.assertEqual(host.read_message(buffer), {"cmd": "start"})

    def test_eof_returns_none(self):
        self.assertIsNone(host.read_message(io.BytesIO(b"")))

    def test_short_header_returns_none(self):
        self.assertIsNone(host.read_message(io.BytesIO(b"\x01\x02")))

    def test_oversized_length_returns_none(self):
        buffer = io.BytesIO(struct.pack("<I", 2_000_000))
        self.assertIsNone(host.read_message(buffer))

    def test_bad_json_returns_empty_dict(self):
        buffer = io.BytesIO(struct.pack("<I", 4) + b"junk")
        self.assertEqual(host.read_message(buffer), {})

    def test_non_object_returns_empty_dict(self):
        buffer = io.BytesIO(struct.pack("<I", 2) + b"[]")
        self.assertEqual(host.read_message(buffer), {})

    def test_write_message_framing(self):
        out = io.BytesIO()
        with mock.patch.object(host.sys, "stdout") as fake_out:
            fake_out.buffer = out
            host.write_message({"ok": True})
        (length,) = struct.unpack("<I", out.getvalue()[:4])
        self.assertEqual(len(out.getvalue()) - 4, length)
        self.assertEqual(json.loads(out.getvalue()[4:]), {"ok": True})


class HandleTestCase(unittest.TestCase):
    def test_status_running(self):
        with mock.patch.object(host, "bridge_reachable", return_value=True):
            self.assertEqual(host.handle({"cmd": "status"}), {"ok": True, "running": True})

    def test_start_when_already_running(self):
        with mock.patch.object(host, "bridge_reachable", return_value=True):
            self.assertEqual(host.handle({"cmd": "start"}),
                             {"ok": True, "action": "already-running"})

    def test_start_spawns_app_and_waits_for_bridge(self):
        calls = []

        def fake_reachable():
            calls.append(1)
            # first check (before spawn): down; then polls: down, up
            return len(calls) > 2

        with mock.patch.object(host, "bridge_reachable", side_effect=fake_reachable), \
             mock.patch.object(host, "app_command", return_value="/usr/bin/daryafter"), \
             mock.patch.object(host.subprocess, "Popen") as popen, \
             mock.patch.object(host, "POLL_INTERVAL", 0.0):
            self.assertEqual(host.handle({"cmd": "start"}), {"ok": True, "action": "started"})
            popen.assert_called_once()
            args = popen.call_args
            self.assertEqual(args.args[0], ["/usr/bin/daryafter"])
            self.assertTrue(args.kwargs.get("start_new_session"))

    def test_start_without_app_installed(self):
        with mock.patch.object(host, "bridge_reachable", return_value=False), \
             mock.patch.object(host, "app_command", return_value=None):
            self.assertEqual(host.handle({"cmd": "start"}),
                             {"ok": False, "error": "daryafter is not installed"})

    def test_unknown_command(self):
        self.assertFalse(host.handle({"cmd": "frobnicate"})["ok"])


class MainLoopTestCase(unittest.TestCase):
    def test_main_answers_one_message_and_exits_on_eof(self):
        stream = io.BytesIO(encode({"cmd": "status"}) )
        with mock.patch.object(host.sys, "stdin") as fake_in, \
             mock.patch.object(host.sys, "stdout") as fake_out, \
             mock.patch.object(host, "bridge_reachable", return_value=False):
            fake_in.buffer = stream
            out = io.BytesIO()
            fake_out.buffer = out
            code = host.main()
        self.assertEqual(code, 0)
        (length,) = struct.unpack("<I", out.getvalue()[:4])
        reply = json.loads(out.getvalue()[4:4 + length])
        self.assertEqual(reply, {"ok": True, "running": False})


if __name__ == "__main__":
    unittest.main()
