# Daryafter browser extension

One shared WebExtension, assembled into two browser builds:

- **Firefox** — `firefox/manifest.json` (MV3 event-page background, gecko ID).
- **Chrome/Chromium/Edge/Brave** — `chrome/manifest.json` (MV3 service worker).

The HTML, CSS, JavaScript and icons live once in `src/`. Do not copy them into the
browser folders: the manifests point at the shared files, and `build.py` puts them
together.

## Build

    python extension/build.py            # both browsers + ZIPs in dist/extensions/
    python extension/build.py --check    # validate sources only
    python extension/build.py --browser firefox --output /tmp/ext

`dist/extensions/firefox/` and `dist/extensions/chrome/` are complete, independent
packages; the matching ZIP is written next to them.

## Load

- **Firefox:** `about:debugging#/runtime/this-firefox` > *Load Temporary Add-on* >
  pick `dist/extensions/firefox/manifest.json` (or the Firefox ZIP).
- **Chrome/Chromium:** `chrome://extensions` > *Developer mode* > *Load unpacked* >
  pick `dist/extensions/chrome/`.

The packaged daryafter install places the same builds in
`/usr/share/daryafter/extensions/{firefox,chrome}`.

## Auto-start

`native-host/` registers a native messaging host so the extension can start Daryafter
when it is not running. The package installs the Firefox manifest system-wide; for
Chrome/Chromium run `native-host/install.sh` with `CHROME_ID` set to the extension ID.

Auto-download, the "Download with Daryafter" context-menu entry and the auto-start
behaviour are identical in both builds; see the main README's "Browser extension"
section for details.
