/*
 * Daryafter browser extension - content script.
 *
 * Auto-download mode: when the user clicks a download link (an <a download>
 * anchor, or a link whose file extension is on the list from the options
 * page), the click is stopped and the link is handed to Daryafter instead
 * of the browser. Ordinary navigation is never touched.
 */
"use strict";

const api = globalThis.browser ?? globalThis.chrome;

/* Fallback before the background script has written its defaults into storage. */
const FALLBACK = { autoEnabled: false, extensions: [] };

let state = { autoEnabled: false, extensions: new Set() };

loadState();
api.storage.onChanged?.addListener((changes, area) => {
  if (area === "local") loadState();
});

async function loadState() {
  const stored = await api.storage.local.get(FALLBACK);
  state = {
    autoEnabled: Boolean(stored.autoEnabled),
    extensions: new Set((stored.extensions || []).map((x) => String(x).toLowerCase())),
  };
}

function nameFromAnchor(anchor) {
  if (anchor.download) return anchor.download;
  try {
    const name = decodeURIComponent(anchor.pathname.split("/").pop() || "");
    return name || "download";
  } catch (err) {
    return "download";
  }
}

function shouldIntercept(anchor) {
  if (!state.autoEnabled) return false;
  if (!/^https?:/i.test(anchor.href)) return false;          // only plain download links
  if (anchor.hasAttribute("download")) return true;           // <a download> always counts
  const name = decodeURIComponent(anchor.pathname).split("/").pop() || "";
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  return state.extensions.has(name.slice(dot + 1).toLowerCase());
}

function handOver(anchor, event) {
  event.preventDefault();
  event.stopPropagation();
  api.runtime.sendMessage({
    type: "download",
    url: anchor.href,
    referrer: location.href,
    filename: nameFromAnchor(anchor),
  }).catch((err) => { /* background unavailable */ });
}

function onClick(event) {
  if (!state.autoEnabled) return;
  if (event.button !== 0) return;                             // left click only
  if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target.closest?.("a[href]");
  if (!anchor) return;
  if (shouldIntercept(anchor)) handOver(anchor, event);
}

function onAuxClick(event) {
  if (!state.autoEnabled) return;
  if (event.button !== 1) return;                             // middle click
  const anchor = event.target.closest?.("a[href]");
  if (!anchor) return;
  if (shouldIntercept(anchor)) handOver(anchor, event);
}

document.addEventListener("click", onClick, true);
document.addEventListener("auxclick", onAuxClick, true);
