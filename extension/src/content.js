/*
 * Daryafter browser extension - content script.
 *
 * Auto-download mode: when the user clicks a download link (an <a download>
 * anchor, or a link whose file extension is on the list from the options
 * page), the click is stopped and the link is handed to Daryafter instead
 * of the browser. Ordinary navigation is never touched.
 */
"use strict";

const {
  api,
  DEFAULTS,
  basenameFromUrl,
  isHttpUrl,
  matchesExtension,
  safeReferrer,
} = globalThis.DaryafterCommon;

let state = { autoEnabled: false, extensions: [] };

loadState();
api.storage.onChanged?.addListener((changes, area) => {
  if (area === "local") loadState();
});

async function loadState() {
  const stored = await api.storage.local.get({
    autoEnabled: DEFAULTS.autoEnabled,
    extensions: DEFAULTS.extensions,
  });
  state = {
    autoEnabled: Boolean(stored.autoEnabled),
    extensions: Array.isArray(stored.extensions)
      ? stored.extensions.map((item) => String(item).toLowerCase())
      : [],
  };
}

function nameFromAnchor(anchor) {
  if (anchor.download) return anchor.download;
  return basenameFromUrl(anchor.href, "");
}

function shouldIntercept(anchor) {
  if (!state.autoEnabled) return false;
  if (!isHttpUrl(anchor.href)) return false;                  // only plain download links
  if (anchor.hasAttribute("download")) return true;           // <a download> always counts
  return matchesExtension(anchor.href, state.extensions);
}

function handOver(anchor, event) {
  event.preventDefault();
  event.stopPropagation();
  api.runtime.sendMessage({
    type: "download",
    url: anchor.href,
    referrer: safeReferrer(location.href),
    filename: nameFromAnchor(anchor),
  }).catch((err) => { /* background unavailable */ });
}

function onClick(event) {
  if (!state.autoEnabled || event.defaultPrevented) return;
  if (event.button !== 0) return;                             // left click only
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target.closest?.("a[href]");
  if (!anchor) return;
  if (shouldIntercept(anchor)) handOver(anchor, event);
}

function onAuxClick(event) {
  if (!state.autoEnabled || event.defaultPrevented) return;
  if (event.button !== 1) return;                             // middle click
  const anchor = event.target.closest?.("a[href]");
  if (!anchor) return;
  if (shouldIntercept(anchor)) handOver(anchor, event);
}

document.addEventListener("click", onClick, true);
document.addEventListener("auxclick", onAuxClick, true);
