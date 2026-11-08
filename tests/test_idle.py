"""Tests for display-session detection, wayland idle tracking and the idle facade.

The WaylandMonitorTests talk to a tiny real-socket fake compositor
(see tests/wayland_server.py) through libwayland-client, so the exact wire
behavior of daryafter.core.idle_wayland is verified, not just mocked.
"""
import os
import struct
import tempfile
import threading
import time
import unittest
from unittest import mock

from daryafter.core import idle, idle_wayland, session


class SessionTypeTests(unittest.TestCase):
    def test_windows(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}), \
             mock.patch("sys.platform", "win32"):
            self.assertEqual(session.session_type(), session.WINDOWS)

    def test_wayland_display_beats_everything(self):
        env = {"WAYLAND_DISPLAY": "wayland-1", "XDG_SESSION_TYPE": "x11", "DISPLAY": ":1"}
        self.assertEqual(session.session_type(env), session.WAYLAND)

    def test_wayland_socket(self):
        self.assertEqual(session.session_type({"WAYLAND_SOCKET": "7"}), session.WAYLAND)

    def test_xdg_types(self):
        self.assertEqual(session.session_type({"XDG_SESSION_TYPE": "x11"}), session.X11)
        self.assertEqual(session.session_type({"XDG_SESSION_TYPE": "tty"}), session.TTY)
        self.assertEqual(session.session_type({"XDG_SESSION_TYPE": "console"}), session.TTY)
        self.assertEqual(session.session_type({"XDG_SESSION_TYPE": "wayland"}), session.WAYLAND)

    def test_falls_back_to_display(self):
        self.assertEqual(session.session_type({"DISPLAY": ":0"}), session.X11)

    def test_unknown(self):
        self.assertEqual(session.session_type({}), session.UNKNOWN)


class IdleStateTests(unittest.TestCase):
    """The event -> seconds bookkeeping, driven with an invented clock."""

    def _tracker(self, timeout: float = 10.0):
        clock = [1000.0]
        state = idle_wayland.IdleState(timeout=timeout)
        state._now = lambda: clock[0]
        self.clock = clock
        return state

    def test_unknown_startup_is_zero(self):
        state = self._tracker()
        self.assertEqual(state.seconds(), 0.0)

    def test_idled_establishes_the_floor(self):
        state = self._tracker()
        self.clock[0] += 3.0            # 3 s after connecting the timeout was reached
        state.on_idled()
        self.assertAlmostEqual(state.seconds(), 10.0, places=6)
        self.clock[0] += 5.0
        self.assertAlmostEqual(state.seconds(), 15.0, places=6)

    def test_resumed_resets(self):
        state = self._tracker()
        self.clock[0] += 12.0
        state.on_idled()
        self.clock[0] += 1.0
        state.on_resumed()
        self.assertAlmostEqual(state.seconds(), 0.0, places=6)
        self.clock[0] += 4.0
        self.assertAlmostEqual(state.seconds(), 4.0, places=6)

    def test_realistic_timeline(self):
        # resumed at t=1013.5 (input seen), idled at t=1024.0 (>=10 s idle),
        # then time passes in both gaps: the tracker is exact, or errs late.
        state = self._tracker()
        self.clock[0] = 1013.5
        state.on_resumed()
        self.clock[0] = 1017.0
        self.assertAlmostEqual(state.seconds(), 3.5, places=6)
        self.clock[0] = 1024.0
        state.on_idled()
        self.clock[0] = 1028.5
        self.assertAlmostEqual(state.seconds(), 14.5, places=6)   # true idle is 15.0

    def test_unknown_event_gap_reports_zero(self):
        # right after a connect, before any event: unknown stays 0.0
        state = self._tracker()
        self.clock[0] += 2.0
        self.assertEqual(state.seconds(), 0.0)


class FacadeDispatchTests(unittest.TestCase):
    """system_idle_seconds hands the query to the right backend."""

    def test_windows_backend_on_nt(self):
        with mock.patch.object(os, "name", "nt"), \
             mock.patch.object(idle, "_windows_idle_seconds", return_value=4.0) as fake:
            self.assertEqual(idle.system_idle_seconds(), 4.0)
            fake.assert_called_once()

    def test_x11_backend_on_x11(self):
        env = {"DISPLAY": ":99", "XDG_SESSION_TYPE": "x11"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch.object(idle, "_x11_idle_seconds", return_value=2.5) as fake, \
             mock.patch.object(idle, "_wayland_idle_seconds", return_value=99.0) as wl:
            self.assertEqual(idle.system_idle_seconds(), 2.5)
            fake.assert_called_once()
            wl.assert_not_called()

    def test_wayland_backend_on_wayland(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-7"}, clear=True), \
             mock.patch.object(idle, "_wayland_idle_seconds", return_value=6.5) as fake, \
             mock.patch.object(idle, "_x11_idle_seconds", return_value=1.0) as x11:
            self.assertEqual(idle.system_idle_seconds(), 6.5)
            fake.assert_called_once()
            x11.assert_not_called()

    def test_unknown_session_reports_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch.object(idle, "_windows_idle_seconds", return_value=1.0), \
             mock.patch.object(idle, "_x11_idle_seconds", return_value=1.0), \
             mock.patch.object(idle, "_wayland_idle_seconds", return_value=1.0):
            self.assertEqual(idle.system_idle_seconds(), 0.0)

    def test_mutter_fallback_is_guarded(self):
        try:
            from PySide6.QtCore import QCoreApplication  # noqa: F401
        except ImportError:
            self.skipTest("PySide6 is not installed")
        # Without a running Qt application the mutter query must be a no-op.
        self.assertEqual(idle._gnome_mutter_idle_seconds(), 0.0)


@unittest.skipUnless(idle_wayland.client_lib() is not None, "libwayland-client not found")
class WaylandMonitorTests(unittest.TestCase):
    """Full round trip against a tiny fake compositor over a real unix socket.

    Each test runs with a private ``XDG_RUNTIME_DIR`` that must stay set from
    before the monitor thread starts until the fake compositor has served the
    connection (libwayland resolves the socket path at connect time).
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="daryafter-wayland-")
        self.addCleanup(self.tmp.cleanup)
        self.runtime = os.path.join(self.tmp.name, "run")
        os.makedirs(self.runtime, exist_ok=True)

    def in_runtime(self, body):
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.runtime}):
            body()

    def _monitor(self, timeout_ms: int = 200, socket_name: str | None = None):
        # socket_name bypasses WAYLAND_DISPLAY; XDG_RUNTIME_DIR comes from the env.
        return idle_wayland.WaylandIdleMonitor(timeout_ms=timeout_ms,
                                               socket_name=socket_name)

    def _watch(self, server, **kwargs):
        thread = threading.Thread(target=server.run, kwargs=kwargs, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 12.0)
        return thread

    # --- the tests below all need the private runtime env; each is a thin wrapper.
    def test_connects_binds_and_tracks_seconds(self):
        self.in_runtime(self._test_connects_binds_and_tracks_seconds)

    def _test_connects_binds_and_tracks_seconds(self):
        from tests.wayland_server import FakeCompositor

        with FakeCompositor(self.runtime, "wayland-ok") as server:
            self._watch(server, deadline=6.0)
            monitor = self._monitor(socket_name=server.name)
            self.assertEqual(0.0, monitor.idle_seconds())   # starts the monitor thread
            self.assertTrue(server.accepted.wait(timeout=3.0))
            self.assertTrue(server.got_idle_request.wait(timeout=3.0),
                            "compositor never received get_idle_notification")

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline and monitor.idle_seconds() <= 0.0:
                time.sleep(0.05)
            self.assertGreater(monitor.idle_seconds(), 0.0,
                               "the idled event should map to positive idle time")

            self.assertEqual(set(server.bound.values()),
                             {"ext_idle_notifier_v1", "wl_seat"})
            self.assertEqual(len(server.idle_events), 1)
            self.assertEqual(server.idle_events[0][1], 200)  # notification interval kept

    def test_v2_compositor_uses_the_input_only_request(self):
        self.in_runtime(self._test_v2_uses_input_only_request)

    def _test_v2_uses_input_only_request(self):
        from tests.wayland_server import FakeCompositor

        with FakeCompositor(self.runtime, "wayland-v2") as server:
            self._watch(server, deadline=6.0)
            monitor = self._monitor(socket_name=server.name)
            monitor.idle_seconds()
            self.assertTrue(server.got_idle_request.wait(timeout=3.0))
            notifier_id = next(obj for obj, iface in server.bound.items()
                               if iface == "ext_idle_notifier_v1")
            opcodes = {(obj, op) for obj, op, _payload in server.requests}
            self.assertIn((notifier_id, 2), opcodes,
                          "a v2 compositor must be asked for input-only idle")

    def test_resumed_event_stops_the_countup(self):
        self.in_runtime(self._test_resumed_event_stops_the_countup)

    def _test_resumed_event_stops_the_countup(self):
        from tests.wayland_server import FakeCompositor

        with FakeCompositor(self.runtime, "wayland-resume") as server:
            self._watch(server, idled_after=0.05, resumed_after=0.4, deadline=8.0)
            monitor = self._monitor(timeout_ms=100, socket_name=server.name)
            monitor.idle_seconds()
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and monitor.idle_seconds() <= 0.0:
                time.sleep(0.05)
            self.assertGreater(monitor.idle_seconds(), 0.0)

            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline and monitor.idle_seconds() > 0.5:
                time.sleep(0.05)
            self.assertLessEqual(monitor.idle_seconds(), 0.5,
                                 "the resumed event must restart the idle period")

    def test_reconnect_after_dead_compositor(self):
        self.in_runtime(self._test_reconnect_after_dead_compositor)

    def _test_reconnect_after_dead_compositor(self):
        # A first connection is served and then closes; a later query re-tries
        # after the cooldown and reconnects when a compositor appears again.
        from tests.wayland_server import FakeCompositor

        with FakeCompositor(self.runtime, "wayland-drop") as server:
            self._watch(server, deadline=2.0)
            monitor = self._monitor(socket_name=server.name)
            monitor.idle_seconds()
            self.assertTrue(server.accepted.wait(timeout=3.0))

        with FakeCompositor(self.runtime, "wayland-drop") as server2:
            self._watch(server2, deadline=6.0)
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline and not server2.accepted.is_set():
                monitor.idle_seconds()          # keeps nudging reconnects
                time.sleep(0.2)
            self.assertTrue(server2.accepted.is_set(),
                            "monitor should reconnect after the compositor returns")


if __name__ == "__main__":
    unittest.main()
