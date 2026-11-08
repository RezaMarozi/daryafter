"""Wayland user-inactivity detection with no extra dependencies.

Talks to the compositor directly through ``libwayland-client`` (always present
on a Wayland session) and the standard ``ext-idle-notify-v1`` protocol
(supported by wlroots-based compositors such as Hyprland, Sway, River and
gamescope, by KDE Plasma 5.24+, and by Wayfire and other Smithay compositors).

How it works
------------

1. A background thread connects to the compositor socket
   (``wl_display_connect(None)``, so the usual ``WAYLAND_DISPLAY`` socket
   selection applies) and binds two globals: ``ext_idle_notifier_v1`` and one
   ``wl_seat``.
2. It creates a persistent notification with ``get_input_idle_notification``
   (v2: input-only, like the Windows ``GetLastInputInfo`` API and the X11
   XScreenSaver idle - it ignores idle inhibitors), falling back to
   ``get_idle_notification`` on v1 compositors.
3. The compositor sends ``idled`` once the user has been idle for the
   notification interval and ``resumed`` whenever input is seen again. The
   :class:`IdleState` tracker turns these two signals into a continuous
   "seconds since last input" value: an ``idled`` received at time ``r`` means
   the idle period began around ``r - T`` (T = notification interval; a slight
   *underestimate* of the true idle time, so the app lock errs on the safe
   side), and a ``resumed`` at time ``r`` means the user acted at ``r``.

The connection is created lazily on the first query and lives until it dies
(e.g. compositor exit); a later query may start it again after a cooldown.

Everything is best-effort: any failure yields "unknown idle" (0.0), which
leaves the idle-based auto-lock off, as before.
"""
from __future__ import annotations

import ctypes
import logging
import threading
import time

log = logging.getLogger(__name__)

RETRY_DELAY = 5.0                        # seconds between connection attempts
NOTIFY_TIMEOUT_MS = 10_000               # granularity of the reported idle time
_GET_IDLE_NOTIFICATION = 1               # ext_idle_notifier_v1 request opcodes
_GET_INPUT_IDLE_NOTIFICATION = 2


class IdleState:
    """Thread-safe event -> seconds bookkeeping.

    An idled event arrives after the configured timeout. Subtracting that
    timeout gives a conservative estimate of when the idle period began.
    """

    def __init__(self, now=time.monotonic, timeout: float = 10.0):
        self._now = now
        self.timeout = max(timeout, 0.001)
        self._lock = threading.Lock()
        self.idle_start: float | None = None
        self.last_activity: float | None = None

    def on_idled(self) -> None:
        with self._lock:
            start = max(self._now() - self.timeout, 0.0)
            if self.idle_start is None or start < self.idle_start:
                self.idle_start = start

    def on_resumed(self) -> None:
        with self._lock:
            self.idle_start = None
            self.last_activity = self._now()

    def seconds(self) -> float:
        """Seconds since the last user input (0.0 while unknown)."""
        with self._lock:
            now = self._now()
            if self.idle_start is not None:
                return max(0.0, now - self.idle_start)
            if self.last_activity is not None:
                return max(0.0, now - self.last_activity)
            return 0.0


# ---------------------------------------------------------------------------
# Wire structures from wayland-util.h plus the interfaces Daryafter needs.
# Only requests the client sends and the events it must react to are crafted.
# ---------------------------------------------------------------------------
class _WlMessage(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("signature", ctypes.c_char_p),
                ("types", ctypes.POINTER(ctypes.c_void_p))]


class _WlInterface(ctypes.Structure):
    _fields_ = [("name", ctypes.c_char_p),
                ("version", ctypes.c_int),
                ("method_count", ctypes.c_int),
                ("methods", ctypes.POINTER(_WlMessage)),
                ("event_count", ctypes.c_int),
                ("events", ctypes.POINTER(_WlMessage))]


class _WlArgument(ctypes.Union):
    """Per-argument cell; field names follow the libwayland signature letters."""
    _fields_ = [("i", ctypes.c_int32),
                ("u", ctypes.c_uint32),
                ("f", ctypes.c_int32),
                ("s", ctypes.c_void_p),      # borrowed C string or object pointer
                ("o", ctypes.c_void_p),      # wl_proxy pointer, marshaled as its id
                ("n", ctypes.c_uint32),      # 0 => libwayland allocates a new object
                ("a", ctypes.c_void_p),
                ("h", ctypes.c_int32)]


_EMPTY_TYPES = (ctypes.c_void_p * 1)(None)   # shared anchor for zero-type messages


def _msg(name: bytes, signature: bytes, types=()) -> _WlMessage:
    """A message record.

    ``types`` follows the signature characters; a ``None`` in a ``new_id`` slot
    means libwayland takes the interface from the marshal call (its semantics
    for bind-like requests).
    """
    types = tuple(types)
    if types:
        arr = (ctypes.c_void_p * len(types))()
        for i, t in enumerate(types):
            arr[i] = ctypes.cast(ctypes.pointer(t), ctypes.c_void_p) if t is not None else None
        _ANCHORS.append(arr)
        types_ptr = ctypes.cast(arr, ctypes.POINTER(ctypes.c_void_p))
    else:
        types_ptr = ctypes.cast(_EMPTY_TYPES, ctypes.POINTER(ctypes.c_void_p))
    return _WlMessage(name, signature, types_ptr)


_ANCHORS: list = []                          # keeps types arrays alive forever


def _build_interfaces() -> dict:
    """Crafts the interfaces; the anchor arrays live for the process lifetime."""
    seat_methods = (_WlMessage * 3)(
        _msg(b"get_pointer", b"n"), _msg(b"get_keyboard", b"n"), _msg(b"get_touch", b"n"))
    seat_events = (_WlMessage * 1)(_msg(b"capabilities", b"u"))          # version 1 only
    seat = _WlInterface(b"wl_seat", 7, 3, ctypes.pointer(seat_methods[0]),
                        1, ctypes.pointer(seat_events[0]))

    notification_methods = (_WlMessage * 1)(_msg(b"destroy", b""))
    notification_events = (_WlMessage * 2)(_msg(b"idled", b""), _msg(b"resumed", b""))
    notification = _WlInterface(b"ext_idle_notification_v1", 2, 1,
                                ctypes.pointer(notification_methods[0]),
                                2, ctypes.pointer(notification_events[0]))

    notifier_methods = (_WlMessage * 3)(
        _msg(b"destroy", b""),
        _msg(b"get_idle_notification", b"nuo", [notification, None, seat]),
        _msg(b"get_input_idle_notification", b"nuo", [notification, None, seat]))
    notifier = _WlInterface(b"ext_idle_notifier_v1", 2, 3,
                            ctypes.pointer(notifier_methods[0]),
                            0, None)                     # no events on this object

    registry_methods = (_WlMessage * 1)(
        _msg(b"bind", b"usun", [None, None, None, None]))   # 'n' has no fixed type
    registry_events = (_WlMessage * 2)(
        _msg(b"global", b"usu"), _msg(b"global_remove", b"u"))
    registry = _WlInterface(b"wl_registry", 1, 1,
                            ctypes.pointer(registry_methods[0]),
                            2, ctypes.pointer(registry_events[0]))

    return {"seat": seat, "notification": notification,
            "notifier": notifier, "registry": registry,
            # every ctypes array stays referenced for the process lifetime:
            "_arrays": (seat_methods, seat_events, notification_methods,
                        notification_events, notifier_methods,
                        registry_methods, registry_events)}


_IFACES = _build_interfaces()
SEAT, NOTIFICATION, NOTIFIER, REGISTRY = (_IFACES["seat"], _IFACES["notification"],
                                          _IFACES["notifier"], _IFACES["registry"])

_BIND_OPCODE = 0


def _load_client_lib():
    lib = None
    for name in ("libwayland-client.so.0", "libwayland-client.so"):
        try:
            lib = ctypes.CDLL(name)
            break
        except OSError:
            continue
    if lib is None:
        return None
    lib.wl_display_connect.restype = ctypes.c_void_p
    lib.wl_display_connect.argtypes = [ctypes.c_char_p]
    lib.wl_display_disconnect.argtypes = [ctypes.c_void_p]
    lib.wl_display_roundtrip.argtypes = [ctypes.c_void_p]
    lib.wl_display_roundtrip.restype = ctypes.c_int
    lib.wl_display_dispatch.argtypes = [ctypes.c_void_p]
    lib.wl_display_dispatch.restype = ctypes.c_int
    lib.wl_display_get_error.argtypes = [ctypes.c_void_p]
    lib.wl_display_get_error.restype = ctypes.c_int
    lib.wl_proxy_marshal_array_flags.restype = ctypes.c_void_p
    lib.wl_proxy_marshal_array_flags.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_WlInterface), ctypes.c_uint32,
        ctypes.c_uint32, ctypes.POINTER(_WlArgument)]
    lib.wl_proxy_add_listener.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    lib.wl_proxy_add_listener.restype = ctypes.c_int
    lib.wl_proxy_get_version.argtypes = [ctypes.c_void_p]
    lib.wl_proxy_get_version.restype = ctypes.c_uint
    return lib


_LIB: object | None = None


def client_lib():
    """The epoll-based wayland client library with our signatures attached (or None)."""
    global _LIB
    if _LIB is None:
        _LIB = _load_client_lib()
    return _LIB


def _interface_bytes() -> dict[str, ctypes._CData]:
    """Interned C strings for bind requests (must outlive every call)."""
    return {"ext_idle_notifier_v1": ctypes.c_char_p(b"ext_idle_notifier_v1"),
            "wl_seat": ctypes.c_char_p(b"wl_seat")}


_BIND_NAMES = _interface_bytes()


def _registry_global_listener() -> tuple:
    """Listener that records advertised globals (binding happens after the roundtrip)."""
    found = {}
    lock = threading.Lock()

    @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_uint, ctypes.c_char_p, ctypes.c_uint)
    def on_global(_data, _registry, name, interface, version):
        try:
            ifn = interface.decode() if interface else ""
        except UnicodeDecodeError:
            ifn = ""
        with lock:
            found.setdefault(ifn, (int(name), int(version)))

    @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint)
    def on_global_removed(_data, _registry, _name):
        pass                       # our bindings are short-lived; a future roundtrip re-syncs

    array = (ctypes.c_void_p * 2)(ctypes.cast(on_global, ctypes.c_void_p),
                                  ctypes.cast(on_global_removed, ctypes.c_void_p))
    return (found, (on_global, on_global_removed), array)


class WaylandIdleMonitor:
    """Owns the compositor connection and converts protocol events into idle
    seconds. Thread-safe for concurrent :meth:`idle_seconds` queries."""

    def __init__(self, timeout_ms: int = NOTIFY_TIMEOUT_MS, lib=None,
                 now=time.monotonic, socket_name: str | None = None):
        self.timeout_ms = timeout_ms
        self._now = now
        self._lib = lib if lib is not None else client_lib()
        self._socket_name = socket_name
        self.state = IdleState(now=now, timeout=timeout_ms / 1000.0)
        self.protocol_missing = False    # session is wayland, compositor lacks the protocol
        self.disconnected = True         # no live connection at this moment
        self._thread: threading.Thread | None = None
        self._soft_stop = threading.Event()
        self._last_attempt = 0.0
        self._lifecycle_lock = threading.Lock()

    @property
    def available(self) -> bool:
        return self._lib is not None

    @property
    def attempted(self) -> bool:
        with self._lifecycle_lock:
            return self._thread is not None

    def running(self) -> bool:
        with self._lifecycle_lock:
            thread = self._thread
            return thread is not None and thread.is_alive() and not self.disconnected

    def idle_seconds(self) -> float:
        """Best current guess of the idle seconds, starting the monitor if needed."""
        self._ensure_started()
        with self._lifecycle_lock:
            state = self.state
        return state.seconds()

    def stop(self) -> None:
        self._soft_stop.set()

    # ------------------------------------------------------------------
    def _ensure_started(self) -> None:
        if self._soft_stop.is_set() or not self.available:
            return

        with self._lifecycle_lock:
            if self.protocol_missing:
                return

            thread = self._thread
            if thread is not None and thread.is_alive():
                return

            now = self._now()
            if thread is not None and now - self._last_attempt < RETRY_DELAY:
                return

            self._last_attempt = now
            self.disconnected = True
            self.state = IdleState(now=self._now, timeout=self.timeout_ms / 1000.0)
            thread = threading.Thread(
                target=self._run,
                daemon=True,
                name="daryafter-wayland-idle",
            )
            self._thread = thread
            thread.start()

    def _run(self) -> None:
        lib = self._lib
        if self._soft_stop.is_set():
            return

        connect_name = self._socket_name.encode() if self._socket_name else None
        display = None
        try:
            display = lib.wl_display_connect(connect_name)
            if not display:
                log.debug("wayland: could not connect to the compositor socket")
                return
            self._pump(lib, display)
        except Exception:
            log.exception("wayland: idle monitor failed")
        finally:
            with self._lifecycle_lock:
                self.disconnected = True
            if display:
                try:
                    lib.wl_display_disconnect(display)
                except Exception:
                    log.debug("wayland: error while disconnecting", exc_info=True)

    def _pump(self, lib, display) -> None:
        found, callbacks, listener_array = _registry_global_listener()

        args = (_WlArgument * 1)()
        args[0].n = 0
        registry = lib.wl_proxy_marshal_array_flags(display, 1, REGISTRY, 1, 0, args)
        if not registry:
            return
        if lib.wl_proxy_add_listener(registry, ctypes.cast(listener_array, ctypes.c_void_p),
                                     None) < 0:
            return
        if lib.wl_display_roundtrip(display) < 0:
            return

        notify_version = min(found.get("ext_idle_notifier_v1", (0, 0))[1], 2)
        if not notify_version:                    # compositor without idle notifications
            with self._lifecycle_lock:
                self.protocol_missing = True
            log.info("wayland: compositor has no ext_idle_notify_v1; "
                     "idle detection falls back to the desktop's own service")
            return
        seat_version = min(found.get("wl_seat", (0, 0))[1], 1)
        if not seat_version:
            return                                 # no seat: nothing to observe input on

        manager = self._bind(lib, registry, found["ext_idle_notifier_v1"][0],
                             notify_version, NOTIFIER)
        seat = self._bind(lib, registry, found["wl_seat"][0], seat_version, SEAT)
        if not manager or not seat:
            return

        note = self._create_notification(lib, manager, seat, notify_version)
        if not note:
            return

        note_callbacks, note_array = _notification_listener(self.state)
        if lib.wl_proxy_add_listener(note, ctypes.cast(note_array, ctypes.c_void_p),
                                     None) < 0:
            return

        with self._lifecycle_lock:
            self.disconnected = False               # live: events may flow
        while not self._soft_stop.is_set():
            if lib.wl_display_dispatch(display) < 0:
                code = lib.wl_display_get_error(display)
                log.info("wayland idle monitor: dispatch error %d (connection lost)", code)
                break

    def _bind(self, lib, registry, global_name: int, version: int,
              iface: _WlInterface):
        """Same as wl_registry_bind(): name, interface string, version, new id."""
        args = (_WlArgument * 4)()
        args[0].u = global_name
        args[1].s = ctypes.cast(_BIND_NAMES[iface.name.decode()], ctypes.c_void_p)
        args[2].u = version
        args[3].n = 0
        proxy = lib.wl_proxy_marshal_array_flags(registry, _BIND_OPCODE, iface,
                                                 version, 0, args)
        if not proxy:
            log.info("wayland: could not bind %r", iface.name.decode())
        return proxy

    def _create_notification(self, lib, manager, seat, version: int):
        opcode = _GET_INPUT_IDLE_NOTIFICATION if version >= 2 else _GET_IDLE_NOTIFICATION
        args = (_WlArgument * 3)()
        args[0].n = 0
        args[1].u = self.timeout_ms
        args[2].o = seat
        note = lib.wl_proxy_marshal_array_flags(manager, opcode, NOTIFICATION,
                                                version, 0, args)
        if not note:
            log.info("wayland: could not create an idle notification object")
        return note


def _notification_listener(state: IdleState):
    """Listener for the two no-argument events of ext_idle_notification_v1."""

    @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
    def on_idled(_data, _note):
        try:
            state.on_idled()
        except Exception:
            log.exception("wayland idle monitor: failed to handle an idle event")

    @ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)
    def on_resumed(_data, _note):
        try:
            state.on_resumed()
        except Exception:
            log.exception("wayland idle monitor: failed to handle a resume event")

    array = (ctypes.c_void_p * 2)(ctypes.cast(on_idled, ctypes.c_void_p),
                                  ctypes.cast(on_resumed, ctypes.c_void_p))
    return (on_idled, on_resumed), array


_monitor_singleton: WaylandIdleMonitor | None = None
_monitor_lock = threading.Lock()


def monitor() -> WaylandIdleMonitor:
    """The process-wide monitor (created on first use, reused afterwards)."""
    global _monitor_singleton
    with _monitor_lock:
        if _monitor_singleton is None:
            _monitor_singleton = WaylandIdleMonitor()
        return _monitor_singleton


def wayland_idle_seconds() -> float:
    """Seconds of user inactivity on the wayland session (0.0 when unknown)."""
    mon = monitor()
    return mon.idle_seconds()
