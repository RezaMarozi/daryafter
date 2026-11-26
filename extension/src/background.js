/*
 * Daryafter browser extension - background script.
 *
 * Talks to the Daryafter download manager through its small localhost
 * bridge (http://127.0.0.1:PORT). Daryafter must be running for this to
 * work; the extension shows a notification when it is not, and asks the
 * native messaging host to start it when possible.
 *
 * The server requires the custom "X-Daryafter-Client" header: ordinary
 * web pages cannot send it (CORS pre-flight fails), so no web site can
 * abuse this bridge by itself - only this extension can.
 */
"use strict";

/* Chrome loads only background.js as the service worker, so pull in the
   shared helpers there. Firefox loads common.js from background.scripts. */
if (!globalThis.DaryafterCommon && typeof importScripts === "function") {
  importScripts("common.js");
}

const {
  api,
  DEFAULTS,
  CLIENT_HEADER,
  basenameFromUrl,
  matchesExtension,
  safeReferrer,
  serverUrl,
} = globalThis.DaryafterCommon;

const MENU_ID = "daryafter-download";

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

/* ---- server bridge ---------------------------------------------------- */

async function sendToDaryafter(url, referrer, filename, settings) {
  let response;
  try {
    response = await fetch(serverUrl("/add", settings), {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json", ...CLIENT_HEADER },
      body: JSON.stringify({
        url,
        referrer: safeReferrer(referrer),
        filename: String(filename ?? "").trim(),
      }),
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
      cache: "no-store",
      headers: CLIENT_HEADER,
    });
    return response.ok;
  } catch (err) {
    return false;
  }
}

/* Ask the native messaging host to start Daryafter when it is not running. */
function nativeStart() {
  return new Promise((resolve) => {
    let port;
    try {
      port = api.runtime.connectNative("daryafter");
    } catch (err) {
      resolve({ ok: false, error: String(err) });      // no host registered
      return;
    }
    if (!port) {
      resolve({ ok: false, error: "Native messaging is unavailable" });
      return;
    }
    let settled = false;
    const done = (value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try { port.disconnect(); } catch (err) { /* already gone */ }
      resolve(value);
    };
    const timer = setTimeout(() => done({ ok: false, error: "timeout" }), 15000);
    port.onMessage.addListener((msg) => {
      done(msg && msg.ok ? msg : { ok: false, error: (msg && msg.error) || "host refused" });
    });
    port.onDisconnect.addListener(() => {
      const err = api.runtime.lastError;               // only valid during disconnect
      done({ ok: false, error: err ? String(err.message || err) : "host exited" });
    });
    port.postMessage({ cmd: "start" });
  });
}

/* Wait until the bridge answers, up to `ms`. */
async function waitUntilRunning(settings, ms) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    if (await pingServer(settings)) return true;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
  return false;
}

/* Send a link, starting Daryafter through the native host when needed. */
async function sendToDaryafterWithStart(url, referrer, filename, settings) {
  let result = await sendToDaryafter(url, referrer, filename, settings);
  if (result.offline) {
    const started = await nativeStart();
    if (started.ok) {
      if (await waitUntilRunning(settings, 15000)) {
        result = await sendToDaryafter(url, referrer, filename, settings);
      } else {
        result = { ok: false, offline: true, error: "Daryafter did not come up" };
      }
    } else {
      result = { ...result, error: started.error || result.error };
    }
  }
  return result;
}

/* ---- small user feedback ---------------------------------------------- */

function setBadge(text, color) {
  const target = api.action ?? api.browserAction;
  if (!target) return;
  try {
    const maybe = target.setBadgeText({ text });
    if (maybe && typeof maybe.catch === "function") maybe.catch(() => {});
    const colorMaybe = target.setBadgeBackgroundColor({ color });
    if (colorMaybe && typeof colorMaybe.catch === "function") colorMaybe.catch(() => {});
    if (text) {
      setTimeout(() => {
        try {
          const clear = target.setBadgeText({ text: "" });
          if (clear && typeof clear.catch === "function") clear.catch(() => {});
        } catch (err) { /* no badge support */ }
      }, 3000);
    }
  } catch (err) { /* no badge support */ }
}

function notify(title, message) {
  if (!api.notifications) return;
  try {
    const maybe = api.notifications.create({
      type: "basic",
      iconUrl: api.runtime.getURL("icons/icon48.png"),
      title,
      message,
    });
    if (maybe && typeof maybe.catch === "function") maybe.catch(() => {});
  } catch (err) { /* notifications unavailable */ }
}

function reportResult(result, url) {
  if (result.ok) {
    setBadge("OK", "#0B7F99");
    return;
  }
  setBadge("!", "#B03030");
  if (result.offline) {
    notify("Daryafter is not running",
           "Start Daryafter, then try the download again.");
  } else {
    notify("Daryafter refused the link", `${result.error || "Unknown error"}\n${url}`);
  }
}

/* ---- context menu: "Download with Daryafter" --------------------------- */

function removeAllMenus() {
  return new Promise((resolve) => {
    try {
      const maybe = api.contextMenus.removeAll(() => resolve());
      if (maybe && typeof maybe.then === "function") maybe.then(resolve, resolve);
    } catch (err) {
      resolve();
    }
  });
}

async function setupMenu() {
  if (!api.contextMenus) return;
  const settings = await loadSettings();
  const suffix = settings.autoEnabled ? " (auto-download is on)" : "";
  await removeAllMenus();
  try {
    const maybe = api.contextMenus.create({
      id: MENU_ID,
      title: `Download with Daryafter${suffix}`,
      contexts: ["link", "image", "video", "audio"],
    }, () => { void api.runtime.lastError; });
    if (maybe && typeof maybe.catch === "function") maybe.catch(() => {});
  } catch (err) { /* menus unavailable */ }
}

api.runtime.onInstalled?.addListener(() => { ensureSettings(); setupMenu(); });
api.runtime.onStartup?.addListener(() => { ensureSettings(); setupMenu(); });
api.storage.onChanged?.addListener(() => { setupMenu(); });
ensureSettings();
setupMenu();

api.contextMenus?.onClicked.addListener((info, tab) => {
  const url = info.linkUrl || info.srcUrl || info.frameUrl || info.pageUrl;
  if (!url) return;
  const referrer = safeReferrer((tab && tab.url) || "");
  const filename = basenameFromUrl(url, "");
  handleDownload(url, referrer, filename);
});

/* ---- messages from the content script / pop-up / options --------------- */

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    const settings = await loadSettings();
    switch (msg && msg.type) {
      case "ping":
        sendResponse({ running: await pingServer(settings) });
        return;
      case "shouldIntercept":
        sendResponse({
          intercept: Boolean(settings.autoEnabled)
            && matchesExtension(msg.href, settings.extensions),
        });
        return;
      case "download": {
        const result = await sendToDaryafterWithStart(
          msg.url, msg.referrer, msg.filename, settings);
        reportResult(result, msg.url);
        sendResponse(result);
        return;
      }
      case "startDaryafter": {
        const started = await nativeStart();
        const running = started.ok && (await waitUntilRunning(settings, 15000));
        sendResponse({ running, error: started.ok ? "" : (started.error || "") });
        return;
      }
    }
    sendResponse({ ok: false, error: "unknown message" });
  })();
  return true;                                      // sendResponse arrives asynchronously
});

async function handleDownload(url, referrer, filename) {
  const settings = await loadSettings();
  const result = await sendToDaryafterWithStart(url, referrer, filename, settings);
  reportResult(result, url);
}
