# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Fixed
- The GNOME Shell idle fallback queried mutter's
  `org.gnome.Mutter.IdleMonitor` D-Bus service on the wrong object path
  (`/org/gnome/Mutter/IdleMonitor`); the interface only exists on the
  `.../IdleMonitor/Core` child object in every Mutter that ships it, so the
  fallback always resolved to "idle unknown" and the auto-lock never armed
  on GNOME desktops. Verified live against mutter 51.1.

### Added
- **Browser extension (beta)** for Firefox and Chrome/Chromium/Edge/Brave, shipped in
  `extension/`:
  - a right-click **"Download with Daryafter"** context-menu entry for links, images, videos
    and audio;
  - an optional **auto-download** mode that hands every clicked download link to Daryafter
    instead of the browser (`<a download>` links plus a configurable list of file types;
    PDF excluded by default);
  - communication over a small localhost bridge inside the app (`core/browser_server.py`,
    port 27240): loopback only, requires a custom header and refuses requests whose origin
    is a web page, so hostile sites cannot forge requests; switch it off in Settings >
    General. Extension-provided file names are honoured; the add dialog still appears when
    "Ask for the file name" is on.
  - **auto-start**: when the bridge is unreachable, the extension starts Daryafter through a
    native messaging host (`extension/native-host/`; installed system-wide by the package for
    Firefox, `install.sh` for Chrome/Chromium), and the pop-up offers a Start button.
    Covered by 13 tests in `tests/test_native_host.py`.
  - Covered by 14 new tests in `tests/test_browser_server.py` (suite: 128 passed) and verified
    live: ping OK, refused web origin, accepted extension request, clicked-download
    interception, normal-link pass-through, and a real auto-start (app down -> click ->
    app started -> download added) driven through headless Firefox.
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
