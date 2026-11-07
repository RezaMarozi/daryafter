# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- Native Wayland session support:
  - Idle-time detection now works on Wayland compositors (used by the app-lock
    auto-lock timer). It uses the `ext-idle-notify-v1` compositor protocol
    directly over `libwayland-client` (no new dependencies), with a fallback to
    GNOME Mutter's `org.gnome.Mutter.IdleMonitor` D-Bus interface on compositors
    that do not expose the protocol.
  - Session-type detection (`daryafter/core/session.py`) that mirrors how Qt
    picks its platform plugin, so idle detection and startup behave consistently.
- On Wayland sessions the application now sets a desktop file name
  (`daryafter`), so the window gets a proper app identity (useful for docking,
  taskbars and window rules).

### Changed
- If the Wayland platform plugin fails to start on a Wayland session, the app
  automatically retries with the X11 (`xcb`) plugin instead of aborting.
- The default interface font on Linux is now the system font (clamped to a
  readable size) instead of the Windows-only "Segoe UI 10pt" setting; Windows
  behaviour is unchanged.

### Known limitations
- Wayland idle detection requires the compositor to advertise
  `ext-idle-notify-v1`, or provide Mutter's idle-monitor D-Bus API.
  If neither source is available, automatic idle-based locking is unavailable.
  Daryafter deliberately does not fall back to X11 idle detection on Wayland.
- Wayland remote-control and notification features beyond idle detection are
  outside the scope of this change.

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
