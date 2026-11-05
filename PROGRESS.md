# Build progress
- [x] Stage 1: engine, tests, command-line tool (30 tests pass on Linux with a local server)
- [x] Stage 2: main window, add dialog with editable name, list, pause/resume, offline mode
- [x] Stage 3: speed chart, min/max/avg, settings dialog, icons, tray, clipboard offer, summary window
- [x] Stage 4: app lock (password, auto-lock, cooldown), private-mode polish, clear history (50 tests pass + UI smoke)
- [x] Stage 5: timers (start / stop / disconnect at a time of day, once or repeating), queue order and position in the window

Before the Linux port, Windows testing was limited: the GUI was only smoke-tested with a fake Qt (tests/ui_smoke.py),
and the engine only with a stdlib HTTP client, not the real httpx.

## Linux port

- [x] Linux launcher with first-run virtual environment setup
- [x] System sleep inhibition while downloads are active
- [x] X11 idle-time detection
- [x] System theme detection through the desktop portal
- [x] Manually launched and tested on Arch Linux with Python 3.14.9
- [x] Test suite: 66 passed

Wayland idle-time detection is not currently supported. Windows still needs
retesting after the Linux changes.
