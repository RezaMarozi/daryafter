# Daryafter browser extension

One extension, two manifests (the browsers need different shapes):

- **Firefox**: `../manifest.json` (folder root, MV3 event-page background).
  Load it in `about:debugging#/runtime/this-firefox` > *Load Temporary Add-on* —
  picking **any file in this folder** works, because the Firefox manifest is the
  folder's `manifest.json`.
- **Chrome/Chromium/Edge/Brave**: `chrome/manifest.json` (MV3 service worker).
  Load it via `chrome://extensions` > *Developer mode* > *Load unpacked* >
  select the `chrome/` folder.

Auto-download, the "Download with Daryafter" context-menu entry and the
auto-start behaviour are identical in both; see the main README's
"Browser extension" section for details.
