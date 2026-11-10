# Build progress

- [x] Stage 1: engine, tests, command-line tool (30 tests pass on Linux with a local server)
- [x] Stage 2: main window, add dialog with editable name, list, pause/resume, offline mode
- [x] Stage 3: speed chart, min/max/avg, settings dialog, icons, tray, clipboard offer, summary window
- [x] Stage 4: app lock (password, auto-lock, cooldown), private-mode polish, clear history (50 tests pass + UI smoke)
- [x] Stage 5: timers (start / stop / disconnect at a time of day, once or repeating), queue order and position in the window

## Platform and Python testing

Tested on:

- Windows 10 and Windows 11
- Python 3.12, 3.13, and 3.14

Before the Linux port, Windows testing was limited: the GUI was only smoke-tested with a fake Qt (tests/ui_smoke.py), and the engine only with a stdlib HTTP client, not the real httpx.

## Linux port

- [x] Linux launcher with first-run virtual environment setup
- [x] System sleep inhibition while downloads are active
- [x] X11 idle-time detection
- [x] System theme detection through the desktop portal
- [x] Native Wayland session support (session-type detection that mirrors Qt, an automatic
      `xcb` fallback when the Wayland plugin fails, `daryafter` window identity, portal-based
      theme detection) and Wayland idle-time detection: the standard `ext-idle-notify-v1`
      protocol over `libwayland-client`, with a Mutter `IdleMonitor` D-Bus fallback for
      compositors without the protocol (the interface lives on the
      `/org/gnome/Mutter/IdleMonitor/Core` child object; verified live against mutter 51.1)
- [x] Manually launched and tested on Arch Linux with Python 3.14.9 under Hyprland; the Mutter
      fallback was exercised in-process against a real, headless GNOME Shell on a private
      D-Bus session (no system or desktop changes)
- [x] Test suite: 101 passed (`python -m pytest -q`), plus `python -m tests.ui_smoke`

Windows still needs retesting after the Linux changes.

The project has also had Linux-side development and test runs. See the relevant pull request and its test notes for Linux-specific coverage.
