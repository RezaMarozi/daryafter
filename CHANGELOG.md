# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [0.1.0] - first public beta

### Added
- Multi-connection, resumable downloads with dynamic re-splitting, retries and per-download / global speed limits.
- Main window: list with progress, filters, search, Add-link dialog (you choose the file name), pause / resume /
  remove / rename, refresh expired links, offline mode, light/dark theme.
- Live speed chart with average / maximum / minimum, connection map, summary window, notification-area icon,
  offer to download copied links.
- App lock with a password (auto-lock, lock on minimize, wrong-password cool-down), `--reset-lock`.
- Private mode (`--private`, `run_private.bat`, or "Start in private mode") and `--normal` to start normally.
- Clear history that also wipes the database file; "Remember passwords" can be switched off and erases saved ones.
- Timers (start / stop / disconnect at a time of day) and a visible queue with move up / down / top / bottom.
- Command-line downloader (`run_cli.bat`).
- `run.bat` installs libraries from a `Libs` folder (no internet needed) and falls back to the internet.
- About window (More menu).

### Known limitations
- Only tested with Python 3.12.10 on 64-bit Windows; the interface has been smoke-tested with a fake Qt on Linux.
- English interface only.
- The app lock hides the window; it does not encrypt data.
