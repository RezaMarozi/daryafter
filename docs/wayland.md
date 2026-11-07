# Wayland and X11 support

Daryafter uses Qt 6 for its interface, so it runs natively on both Wayland and X11. The platform is
selected automatically from the user session; Daryafter does not force XWayland and does not require
any X11 libraries on a Wayland desktop.

## Choosing the backend

Qt reads the session variables (`XDG_SESSION_TYPE`, `WAYLAND_DISPLAY`, `DISPLAY`) and loads its Wayland
or X11 platform plugin. Daryafter records the detected session and the actual Qt platform in
`daryafter.log`, for example:

    Display server: wayland; Qt platform: wayland

To test a specific backend, set `QT_QPA_PLATFORM` before starting the app:

    QT_QPA_PLATFORM=wayland ./run.sh
    QT_QPA_PLATFORM=xcb ./run.sh          # run through XWayland/X11

The application id on Wayland is `daryafter`, which matches `packaging/daryafter.desktop`. This lets the
compositor find the installed icon and group the window correctly. The Arch package depends on
`qt6-wayland`; the PySide6 wheels and the AppImage bundle the Wayland platform plugin themselves.

## Inactivity detection (automatic app lock)

On X11, Daryafter queries the XScreenSaver extension.

On Wayland, Daryafter first uses the standard `ext-idle-notify-v1` protocol.
The compositor reports idle and resumed events for the active seat. This is
handled by a background thread, so polling the idle timer does not block the
GUI thread. Compositors that advertise protocol version 2 use its input-only
notification request; version 1 is also supported.

If the compositor does not advertise this protocol, Daryafter tries Mutter's
`org.gnome.Mutter.IdleMonitor.GetIdletime` D-Bus API. This provides a fallback
for GNOME/Mutter sessions. Other compositors without `ext-idle-notify-v1` or
a compatible Mutter service cannot provide automatic inactivity detection.

Daryafter never falls back to X11 idle time on a Wayland session: under
XWayland that would only observe input sent to X11 clients and could lock the
app while the user is working in native Wayland windows.

If no supported idle source is available, automatic inactivity locking is
unavailable. Manual locking, lock-on-minimize, and other app-lock controls
remain available.

## Tray icon and notifications

Tray icons use Qt's StatusNotifierItem support. A host such as KDE Plasma, or a GNOME extension that
provides one, is required; GNOME's default Wayland session has no tray. If the tray is unavailable,
Daryafter sends completion and timer notifications through `notify-send`, provided by `libnotify`,
when a compatible freedesktop.org notification daemon (`org.freedesktop.Notifications`) is running.
`libnotify` is an optional runtime dependency on Arch Linux. The in-app notification setting is
independent of the tray setting.

## Wayland limitations

Wayland deliberately gives applications less control over windows and global input:

- the compositor decides window placement and whether a request to raise/focus a window is honoured;
- global keyboard shortcuts are not available to normal applications, so shortcuts work while a
  Daryafter window is focused;
- clipboard access and opening files/folders go through Qt and the desktop portal and work normally;
- screen sleep inhibition still uses `systemd-inhibit`, which is session-type independent.

## Testing

    python -m unittest discover -s tests -t .
    python -m tests.ui_smoke

Most Wayland protocol tests use a local fake compositor and do not require a
real desktop session. The Mutter fallback requires a GNOME/Mutter D-Bus
session for live testing.
