"""A fake Wayland compositor for the idle-monitor tests.

Speaks just enough of the wire protocol to be a compositor:
- answers wl_display.get_registry with two globals (ext_idle_notifier_v1 v2, wl_seat v9),
- answers wl_display.sync with a wl_callback.done (needed by roundtrip),
- accepts ext_idle_notifier_v1 binds,
- and on get_idle_notification / get_input_idle_notification sends an `idled`
  event after a delay, with an optional later `resumed`.
"""
import os
import socket
import struct
import threading
import time


def u32(value: int) -> bytes:
    return struct.pack("<I", value & 0xFFFFFFFF)


def wire_str(s: str) -> bytes:
    raw = s.encode()
    pad = -(len(raw) + 1) % 4
    return u32(len(raw) + 1) + raw + b"\x00" + b"\x00" * pad


def event(obj_id: int, opcode: int, payload: bytes = b"") -> bytes:
    return struct.pack("<II", obj_id, ((8 + len(payload)) << 16) | opcode) + payload


class FakeCompositor:
    """Run with a context manager; exposes the requests it received."""

    def __init__(self, directory: str, name: str = "wayland-daryafter-tests"):
        self.path = os.path.join(directory, name)
        self.name = name
        self.requests: list[tuple[int, int, bytes]] = []   # (object id, opcode, payload)
        self.idle_events: list[tuple[int, int]] = []       # (new_id, timeout) seen so far
        self.bound: dict[int, str] = {}                    # object id -> interface name
        self.got_idle_request = threading.Event()
        self._lock = threading.Lock()

    def __enter__(self):
        if os.path.exists(self.path):
            os.unlink(self.path)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(1)
        self.server.settimeout(10)
        self.accepted = threading.Event()
        return self

    def __exit__(self, *exc):
        self.server.close()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def run(self, idled_after: float = 0.05, resumed_after: float = 0.0, deadline: float = 8.0):
        """Serve one connection until it drops or the deadline passes."""
        try:
            connection, _ = self.server.accept()
        except OSError:
            return
        connection.settimeout(deadline)
        self.accepted.set()
        buffer = b""
        end = time.monotonic() + deadline

        while time.monotonic() < end:
            try:
                chunk = connection.recv(4096)
            except (socket.timeout, OSError):
                break
            if not chunk:
                break
            buffer += chunk
            while len(buffer) >= 8:
                obj, size_opcode = struct.unpack("<II", buffer[:8])
                opcode = size_opcode & 0xFFFF
                size = size_opcode >> 16
                if size < 8:
                    connection.close()
                    return
                if len(buffer) < size:
                    break                                  # wait for the rest
                body = buffer[8:size]
                buffer = buffer[size:]
                with self._lock:
                    self.requests.append((obj, opcode, body))
                ints = [struct.unpack("<I", body[i:i + 4])[0]
                        for i in range(0, len(body) - len(body) % 4, 4)]
                new_id = ints[0] if ints else 0

                if obj == 1 and opcode == 1:               # wl_display.get_registry
                    for slot, (ifn, ver) in enumerate(
                            [("ext_idle_notifier_v1", 2), ("wl_seat", 9)], start=1):
                        payload = u32(slot) + wire_str(ifn) + u32(ver)
                        connection.sendall(event(new_id, 0, payload))
                elif obj == 1 and opcode == 0:             # wl_display.sync
                    connection.sendall(event(new_id, 0, u32(1)))   # wl_callback.done
                elif obj == 2 and opcode == 0:             # wl_registry.bind
                    name = ints[0]
                    length = ints[1]
                    iface = body[8:8 + length - 1].decode()
                    tail = body[8 + length + -(length) % 4:]
                    version, new_obj = struct.unpack("<II", tail)
                    self.bound[new_obj] = iface
                elif self.bound.get(obj) == "ext_idle_notifier_v1" and opcode in (1, 2):
                    with self._lock:
                        self.idle_events.append((new_id, ints[1]))
                    self.got_idle_request.set()
                    note_id = new_id
                    def send_event(event_opcode):
                        try:
                            connection.sendall(event(note_id, event_opcode))
                        except OSError:
                            pass

                    if idled_after >= 0:
                        t = threading.Timer(idled_after, send_event, args=(0,))
                        t.daemon = True
                        t.start()
                    if resumed_after > 0:
                        t2 = threading.Timer(
                            idled_after + resumed_after,
                            send_event,
                            args=(1,),
                        )
                        t2.daemon = True
                        t2.start()
        connection.close()
