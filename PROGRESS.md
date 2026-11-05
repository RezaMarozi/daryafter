# Build progress
- [x] Stage 1: engine, tests, command-line tool (30 tests pass on Linux with a local server)
- [x] Stage 2: main window, add dialog with editable name, list, pause/resume, offline mode
- [x] Stage 3: speed chart, min/max/avg, settings dialog, icons, tray, clipboard offer, summary window
- [x] Stage 4: app lock (password, auto-lock, cooldown), private-mode polish, clear history (50 tests pass + UI smoke)
- [x] Stage 5: timers (start / stop / disconnect at a time of day, once or repeating), queue order and position in the window

Not yet run on Windows: the GUI was only smoke-tested with a fake Qt (tests/ui_smoke.py),
and the engine only with a stdlib HTTP client, not the real httpx.
