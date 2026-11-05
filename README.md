# Daryafter

Free, open-source download manager for Windows 10/11. Multi-connection downloads that can be paused
and resumed, a queue, timers, an app lock and a private mode.

> **Status: Beta (0.1.0).** Tested with **Python 3.12.10** on 64-bit Windows only. Python 3.13 and 3.14
> may work but have not been tested. Expect rough edges; please report them in
> [Issues](https://github.com/RezaMarozi/daryafter/issues).

## Screenshots

Screenshots are coming soon.

<!-- When the images are ready, put them in docs/screenshots/ and uncomment:
![Main window](docs/screenshots/main-window.png)
![Lock screen](docs/screenshots/lock-screen.png)
![Settings](docs/screenshots/settings.png)
-->

## Features

- **Fast, resumable downloads**: 1-32 connections per file, slow parts are re-split dynamically,
  resume after pause, network loss or restart, automatic retry with back-off.
- **Queue and limits**: choose how many downloads run at once, move downloads up or down the queue,
  per-download and global speed limits, "max speed" mode.
- **Live statistics**: speed chart for the last 60 seconds with average / maximum / minimum, and a map
  of what each connection has finished.
- **You choose the file name** before a download starts; names are made Windows-safe and existing files
  are never overwritten by accident.
- **Timers**: start, stop or disconnect at a time of day, once or repeating.
- **Privacy**: app lock with a password, private mode, "clear history" that also wipes the database file.
- **Also**: offline mode, refresh an expired link, optional checksum check, proxy support (system, none
  or manual, including SOCKS), light/dark theme that follows Windows, notification-area icon, an offer to
  download links you copy, and a command-line downloader.

Daryafter downloads plain HTTP/HTTPS file links. It does not do torrents or FTP, and it does not extract
videos from streaming sites (see the [Roadmap](#roadmap)).

## Install

1. Install **Python 3.12.10** from [python.org](https://www.python.org/downloads/release/python-31210/)
   and tick **"Add python.exe to PATH"** in the installer.
2. Download this project (**Code > Download ZIP**) and extract it.
3. Get the libraries (they are not in this repository because `PySide6` is very large). Pick one:
   - **Offline (recommended if your internet is limited):** download `Libs.zip` from
     PASTE_LINK_HERE (more mirrors: PASTE_LINK_HERE) and extract it so that a `Libs` folder sits next to
     `run.bat`. SHA-256 of `Libs.zip`: `PASTE_SHA256_HERE`.
   - **Download them yourself:** get the separate `get_libs.bat` (PASTE_LINK_HERE), put it anywhere and
     double-click it. It creates a `Libs` folder next to itself, trying well-known worldwide mirrors first
     and Iranian mirrors after that. Then move that `Libs` folder next to `run.bat`.
     Mirrors are third parties, so prefer the official PyPI or `Libs.zip` if you can.
   - **Do nothing:** if you have internet, `run.bat` downloads the libraries by itself.
4. Double-click **`run.bat`**. The first run creates a private Python environment (`.venv`) and installs
   the libraries from `Libs` (no internet needed). Later runs start at once.

Options (add them after `run.bat` in a Command Prompt):

| Option | Meaning |
|---|---|
| `--private` | private mode (also: `run_private.bat`) |
| `--normal` | start normally even if "Start in private mode" is ticked in Settings |
| `--portable` | keep data next to the program (also a file named `portable.flag`) |
| `--data-dir FOLDER` | use another folder for the database |
| `--reset-lock` | forgot the password: removes the lock **and** clears the saved list |
| `LINK` | add this link on start |

If the program closes at once, run `.venv\Scripts\python -m daryafter` in a Command Prompt to see the error.
The log file is `%APPDATA%\Daryafter\daryafter.log`.

## App lock, private mode and history

- **App lock** (Settings > Privacy): with a password set, Daryafter starts locked. Downloads keep running
  while locked. It locks again with Ctrl+L, when the window is minimized or sent to the tray, and
  (optional) after N minutes without keyboard or mouse use. Wrong passwords are slowed down (after three
  mistakes: 5 s, 10 s, 20 s ... up to 5 minutes). While locked, notifications and pop-ups show no file names.
  **The lock only hides the window.** It does not encrypt the download list, the settings or your files;
  anyone who can open your Windows account can still read them. A forgotten password cannot be recovered
  (use `--reset-lock`).
- **Private mode**: the list, history and passwords stay in memory only; no database or log file is
  written; unfinished downloads are deleted on exit; notifications show no file names. Finished files stay
  in your download folder, and Windows may list files you open in its own "recent files". The saved
  settings are read without being changed, so the app lock still applies.
- **Clear history** (More menu or Settings > Privacy): removes finished and failed downloads from the list
  and wipes them from the database file. Downloaded files are kept.
- Saved passwords are encrypted with Windows DPAPI (tied to your Windows user) and can be switched off.

## Timers and queue

- **Timers** (Settings > Timers): at a chosen time and days: **Start** (go online and resume paused or
  failed downloads), **Stop** (pause everything) or **Disconnect** (offline mode). Timers run only while
  Daryafter is open. If the computer was asleep through the time, the timer still runs when it wakes, but
  only within 10 minutes of the planned time.
- **Queue**: waiting downloads show their place ("Queued #2"). Right-click a download to move it to the top,
  up, down or to the bottom.

## Command line

    run_cli.bat "https://example.com/big.zip" -o D:\Downloads -c 16

It asks for the file name before downloading, shows live speed and prints the average / maximum / minimum
speed at the end. Options: `-o FOLDER`, `-n NAME`, `-y`, `-c N`, `--limit KB/s`, `--max-speed`
(32 connections), `--sha256 HASH`. It keeps no list: a stopped download is not continued next time.

## Where your data is

`%APPDATA%\Daryafter\` holds `daryafter.db` (download list and settings, including the password hash) and
`daryafter.log`. With `--portable` it is the `data` folder next to the program. Private mode writes nothing.

## Tests

    python -m unittest discover -s tests -t .
    python -m tests.ui_smoke

The engine is tested against a local test server (ranges, resume, restart, flaky connections, limits,
redirects, expired links, checksum, offline mode, queue, timers, app lock, private mode). `ui_smoke` runs
the interface code against a fake Qt, so it catches Python mistakes but not how windows look.

## Third-party libraries

Daryafter uses these libraries (and their own dependencies, which come with them):

| Library | Used for | License |
|---|---|---|
| [PySide6 (Qt for Python)](https://pypi.org/project/PySide6/) | the graphical interface | LGPL v3 (also GPL / commercial) |
| [httpx](https://pypi.org/project/httpx/) | network requests | BSD-3-Clause |
| [truststore](https://pypi.org/project/truststore/) | use the Windows certificate store | MIT |

Check each package page on PyPI for its exact license. The `.whl` files in `Libs.zip` are the unmodified
official packages and carry their own license files.

## Roadmap

Plans, with **no dates and no promises**:

- **Next:** a Windows installer / `.exe` (so Python is not needed); testing and officially supporting
  Python 3.13 and 3.14.
- **Planned:** more interface languages; a browser extension; a check for new versions.
- **Under consideration:** downloading from Instagram and Telegram. This depends on technical
  feasibility and on those services' terms, so it may not happen.

Suggestions are welcome in [Issues](https://github.com/RezaMarozi/daryafter/issues).

## Contributing, security, contact

See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md). Author: Reza Marozi,
<marozireza2010@gmail.com>.

## License

[MIT](LICENSE) © 2026 Reza Marozi
