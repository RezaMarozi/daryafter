/*
 * Daryafter browser extension - background script.
 *
 * Talks to the Daryafter download manager through its small localhost
 * bridge (http://127.0.0.1:PORT). Daryafter must be running for this to
 * work; the extension shows a notification when it is not.
 *
 * The server requires the custom "X-Daryafter-Client" header: ordinary
 * web pages cannot send it (CORS pre-flight fails), so no web site can
 * abuse this bridge by itself - only this extension can.
 */
"use strict";

const api = globalThis.browser ?? globalThis.chrome;

const DEFAULTS = {
  autoEnabled: false,          // auto-download: hand clicked download links to Daryafter
  port: 27240,                 // must match Daryafter's bridge port
  extensions: [
    "7z", "apk", "avi", "bin", "bz2", "cab", "crx", "deb", "dmg", "epub",
    "exe", "flac", "gz", "img", "iso", "mkv", "mov", "mp3", "mp4", "msi",
    "ogg", "pkg", "psd", "rar", "rpm", "tar", "wav", "webm", "xz", "zst", "zip",
  ],
};

const MENU_ID = "daryafter-download";
const CLIENT_HEADER = { "X-Daryafter-Client": "daryafter-extension/1" };

function serverUrl(path, settings) {
  return `http://127.0.0.1:${settings.port || DEFAULTS.port}${path}`;
}

async function loadSettings() {
  const stored = await api.storage.local.get(DEFAULTS);
  return { ...DEFAULTS, ...stored };
}

/* Write any missing settings so content scripts always see full values. */
async function ensureSettings() {
  const stored = await api.storage.local.get(Object.keys(DEFAULTS));
  const missing = {};
  for (const key of Object.keys(DEFAULTS)) {
    if (stored[key] === undefined) missing[key] = DEFAULTS[key];
  }
  if (Object.keys(missing).length) await api.storage.local.set(missing);
}
ensureSettings();
api.runtime.onInstalled?.addListener(ensureSettings);
api.runtime.onStartup?.addListener(ensureSettings);

/* ---- server bridge ---------------------------------------------------- */

async function sendToDaryafter(url, referrer, filename, settings) {
  let response;
  try {
    response = await fetch(serverUrl("/add", settings), {
      method: "POST",
      headers: { "Content-Type": "application/json", ...CLIENT_HEADER },
      body: JSON.stringify({ url, referrer, filename }),
    });
  } catch (err) {
    return { ok: false, offline: true, error: String(err) };
  }
  let data = {};
  try { data = await response.json(); } catch (err) { /* non-JSON reply */ }
  return {
    ok: response.ok && data.ok !== false,
    status: response.status,
    error: data.error || (response.ok ? "" : `HTTP ${response.status}`),
  };
}

async function pingServer(settings) {
  try {
    const response = await fetch(serverUrl("/ping", settings), {
      headers: CLIENT_HEADER,
    });
    return response.ok;
  } catch (err) {
    return false;
  }
}

/* ---- small user feedback ---------------------------------------------- */

function setBadge(text, color) {
  const target = api.action ?? api.browserAction;
  if (!target) return;
  try {
    target.setBadgeText({ text });
    target.setBadgeBackgroundColor({ color });
    if (text) setTimeout(() => target.setBadgeText({ text: "" }), 3000);
  } catch (err) { /* no badge support */ }
}

function notify(title, message) {
  if (!api.notifications) return;
  try {
    api.notifications.create({
      type: "basic",
      iconUrl: api.runtime.getURL("icons/icon48.png"),
      title,
      message,
    });
  } catch (err) { /* notifications unavailable */ }
}

function reportResult(result, url) {
  if (result.ok) {
    setBadge("OK", "#0B7F99");
    return;
  }
  setBadge("!", "#B03030");
  if (result.offline) {
    notify("Daryafter is not running", "Start Daryafter, then try the download again.");
  } else {
    notify("Daryafter refused the link", `${result.error || "Unknown error"}\n${url}`);
  }
}

/* ---- context menu: "Download with Daryafter" --------------------------- */

function basenameFromUrl(url) {
  try {
    const path = new URL(url).pathname;
    const name = decodeURIComponent(path.split("/").pop() || "");
    return name || "download";
  } catch (err) {
    return "download";
  }
}

async function setupMenu() {
  const settings = await loadSettings();
  const suffix = settings.autoEnabled ? " (auto-download is on)" : "";
  if (api.contextMenus?.removeAll) {
    api.contextMenus.removeAll(() => {
      api.contextMenus.create({
        id: MENU_ID,
        title: `Download with Daryafter${suffix}`,
        contexts: ["link", "image", "video", "audio"],
      });
    });
  } else {
    api.contextMenus.create({
      id: MENU_ID,
      title: `Download with Daryafter${suffix}`,
      contexts: ["link", "image", "video", "audio"],
    });
  }
}
setupMenu();
api.storage.onChanged?.addListener(setupMenu);      // keep the "(auto-download is on)" hint fresh

api.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.frameUrl || info.pageUrl;
  if (!url) return;
  handleDownload(url, (tab && tab.url) || "", basenameFromUrl(url));
});

/* ---- messages from the content script / pop-up / options --------------- */

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    const settings = await loadSettings();
    switch (msg.type) {
      case "ping":
        sendResponse({ running: await pingServer(settings) });
        return;
      case "shouldIntercept": {
        if (!settings.autoEnabled) { sendResponse({ intercept: false }); return; }
        sendResponse({ intercept: matchesExtension(msg.href, settings.extensions) });
        return;
      }
      case "download": {
        const result = await sendToDaryafter(msg.url, msg.referrer, msg.filename, settings);
        reportResult(result, msg.url);
        sendResponse(result);
        return;
      }
      case "testDownload": {
        const result = await sendToDaryafter(msg.url, "", "", settings);
        reportResult(result, msg.url);
        sendResponse(result);
        return;
      }
    }
    sendResponse({ ok: false, error: "unknown message" });
  })();
  return true;                                      // sendResponse arrives asynchronously
});

async function handleDownload(url, referrer, filename) {
  const settings = await loadSettings();
  const result = await sendToDaryafter(url, referrer, filename, settings);
  reportResult(result, url);
}

function matchesExtension(url, extensions) {
  if (!url || !/^https?:/i.test(url)) return false;
  let pathname = "";
  try { pathname = new URL(url).pathname; } catch (err) { return false; }
  const name = decodeURIComponent(pathname).split("/").pop() || "";
  const dot = name.lastIndexOf(".");
  if (dot < 0) return false;
  const ext = name.slice(dot + 1).toLowerCase();
  return extensions.some((item) => item.trim().toLowerCase() === ext);
}
