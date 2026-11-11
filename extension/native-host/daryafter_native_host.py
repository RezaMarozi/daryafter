#!/usr/bin/env python
"""Native messaging host for the Daryafter browser extension.

The browser launches this script (registered in a native-messaging-host
manifest) and speaks to it over stdin/stdout: each message is 4 bytes of
little-endian length followed by UTF-8 JSON. The extension connects only
when the Daryafter HTTP bridge is unreachable, so this script's job is
to start Daryafter when it is not running yet.

Protocol from the extension:

    {"cmd": "start"}    start Daryafter if it is not running
    {"cmd": "status"}   report whether Daryafter is reachable

Replies:  {"ok": true,  "action": "started" | "already-running"}
          {"ok": false, "error": "..."}

The host exits when the browser closes the pipe (EOF on stdin).
"""
from __future__ import annotations

import json
import socket
import struct
import subprocess
import sys

BRIDGE_HOST = "127.0.0.1"
BRIDGE_PORT = 27240
CONNECT_TIMEOUT = 0.4
# After spawning, wait for the app to come up before answering, so the
# extension can go straight back to the HTTP bridge.
START_TIMEOUT = 10.0
POLL_INTERVAL = 0.25


def read_message(stream) -> dict | None:
    raw_header = stream.read(4)
    if len(raw_header) < 4:
        return None                                  # EOF: browser hung up
    (length,) = struct.unpack("<I", raw_header)
    if not 0 < length <= 1_048_576:
        return None
    raw = stream.read(length)
    if len(raw) < length:
        return None
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_message(message: dict) -> None:
    raw = json.dumps(message).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(raw)) + raw)
    sys.stdout.buffer.flush()


def bridge_reachable() -> bool:
    try:
        with socket.create_connection((BRIDGE_HOST, BRIDGE_PORT), CONNECT_TIMEOUT):
            return True
    except OSError:
        return False


def app_command() -> str | None:
    from shutil import which

    return which("daryafter")


def start_app() -> str:
    """Spawn Daryafter detached. Returns "started" or "already-running"."""
    if bridge_reachable():
        return "already-running"
    command = app_command()
    if not command:
        raise FileNotFoundError("daryafter is not installed")
    subprocess.Popen(
        [command], start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # Give the app time to open the bridge before answering, so the
    # extension can go straight back to the HTTP bridge.
    import time

    waited = 0.0
    while waited < START_TIMEOUT:
        time.sleep(POLL_INTERVAL)
        waited += POLL_INTERVAL
        if bridge_reachable():
            return "started"                             # slow start; let the extension retry
    return "started"


def handle(message: dict) -> dict:
    command = str(message.get("cmd") or "")
    if command == "status":
        return {"ok": True, "running": bridge_reachable()}
    if command == "start":
        if bridge_reachable():
            return {"ok": True, "action": "already-running"}
        try:
            return {"ok": True, "action": start_app()}
        except FileNotFoundError as exc:
            return {"ok": False, "error": str(exc)}
    return {"ok": False, "error": "unknown cmd: " + (command or "(empty)")}


def main() -> int:
    while True:
        message = read_message(sys.stdin.buffer)
        if message is None:
            return 0
        write_message(handle(message))


if __name__ == "__main__":
    raise SystemExit(main())
