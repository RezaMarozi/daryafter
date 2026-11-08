"""Startup-related unit tests: Qt platform plugin fallback choices on Linux."""
import os
import unittest
from unittest import mock

from daryafter.app import _platform_fallbacks


class PlatformFallbackTests(unittest.TestCase):
    def test_wayland_session_prefers_wayland_then_xwayland(self):
        env = {"WAYLAND_DISPLAY": "wayland-1"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("os.name", "posix"):
            self.assertEqual(_platform_fallbacks(), ["xcb"])

    def test_x11_session_tries_xcb_first(self):
        env = {"DISPLAY": ":0", "XDG_SESSION_TYPE": "x11"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("os.name", "posix"):
            self.assertEqual(_platform_fallbacks(), ["wayland"])

    def test_explicit_qt_qpa_platform_is_respected(self):
        env = {"WAYLAND_DISPLAY": "wayland-1", "QT_QPA_PLATFORM": "xcb"}
        with mock.patch.dict(os.environ, env, clear=True), \
             mock.patch("os.name", "posix"):
            self.assertEqual(_platform_fallbacks(), [])

    def test_windows_never_falls_back(self):
        with mock.patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-1"}), \
             mock.patch("os.name", "nt"):
            self.assertEqual(_platform_fallbacks(), [])

    def test_no_session_hints(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
             mock.patch("os.name", "posix"):
            self.assertEqual(_platform_fallbacks(), ["xcb", "wayland"])


if __name__ == "__main__":
    unittest.main()
