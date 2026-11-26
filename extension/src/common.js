/*
 * Daryafter browser extension - shared helpers.
 *
 * Loaded before the other scripts in every context:
 *   - background: manifest background.scripts (Firefox) / importScripts (Chrome)
 *   - content script: content_scripts js list
 *   - popup/options pages: <script src="common.js">
 *
 * Keep this file free of side effects beyond defining DaryafterCommon, so the
 * Node test suite can load it with a minimal sandbox.
 */
"use strict";

(function (root) {
  const api = root.browser ?? root.chrome;

  const DEFAULTS = {
    autoEnabled: false,          // auto-download: hand clicked download links to Daryafter
    port: 27240,                 // must match Daryafter's bridge port
    extensions: [
      "7z", "apk", "avi", "bin", "bz2", "cab", "crx", "deb", "dmg", "epub",
      "exe", "flac", "gz", "img", "iso", "mkv", "mov", "mp3", "mp4", "msi",
      "ogg", "pkg", "psd", "rar", "rpm", "tar", "wav", "webm", "xz", "zst", "zip",
    ],
  };

  const CLIENT_HEADER = { "X-Daryafter-Client": "daryafter-extension/2" };
  const MIN_PORT = 1024;
  const MAX_PORT = 65535;

  function normalizeExtension(value) {
    return String(value ?? "").trim().toLowerCase().replace(/^\./, "");
  }

  function isExtensionToken(value) {
    return /^[a-z0-9]{1,10}$/.test(value);
  }

  /* Parse the "file types" textarea. Returns accepted tokens (deduplicated)
     and the raw tokens that were rejected, so the UI can explain them. */
  function parseExtensionList(text) {
    const accepted = [];
    const rejected = [];
    const seen = new Set();
    for (const raw of String(text ?? "").split(/[\s,;]+/)) {
      if (!raw.trim()) continue;
      const token = normalizeExtension(raw);
      if (!isExtensionToken(token)) {
        rejected.push(raw.trim());
      } else if (!seen.has(token)) {
        seen.add(token);
        accepted.push(token);
      }
    }
    return { accepted, rejected };
  }

  /* Strict port validation: never silently "fix" what the user typed. */
  function parsePort(value) {
    const text = String(value ?? "").trim();
    if (!/^\d+$/.test(text)) {
      return { ok: false, error: "Enter a whole number between 1024 and 65535." };
    }
    const port = Number(text);
    if (!Number.isInteger(port) || port < MIN_PORT || port > MAX_PORT) {
      return { ok: false, error: `The port must be between ${MIN_PORT} and ${MAX_PORT}.` };
    }
    return { ok: true, port };
  }

  function safeDecode(value) {
    try {
      return decodeURIComponent(value);
    } catch (err) {
      return String(value ?? "");
    }
  }

  function filenameFromPath(pathname, fallback = "") {
    const name = safeDecode(pathname || "").split("/").pop() || "";
    return name || fallback;
  }

  function basenameFromUrl(url, fallback = "") {
    try {
      return filenameFromPath(new URL(url).pathname, fallback);
    } catch (err) {
      return fallback;
    }
  }

  function isHttpUrl(url) {
    return /^https?:\/\//i.test(String(url ?? "").trim());
  }

  /* Only an http(s) page can be a meaningful Referer; anything else
     (file:, about:, extension pages) is dropped instead of failing the
     whole download request. */
  function safeReferrer(value) {
    const text = String(value ?? "").trim();
    return isHttpUrl(text) ? text : "";
  }

  function matchesExtension(url, extensions) {
    if (!isHttpUrl(url)) return false;
    let pathname = "";
    try {
      pathname = new URL(url).pathname;
    } catch (err) {
      return false;
    }
    const name = safeDecode(pathname).split("/").pop() || "";
    const dot = name.lastIndexOf(".");
    if (dot < 0) return false;
    const ext = name.slice(dot + 1).toLowerCase();
    const list = extensions instanceof Set ? [...extensions] : (extensions || []);
    return list.some((item) => normalizeExtension(item) === ext);
  }

  function serverUrl(path, settings) {
    const port = (settings && settings.port) || DEFAULTS.port;
    return `http://127.0.0.1:${port}${path}`;
  }

  function manifestVersion() {
    try {
      return api.runtime.getManifest().version;
    } catch (err) {
      return "";
    }
  }

  root.DaryafterCommon = {
    api,
    DEFAULTS,
    CLIENT_HEADER,
    MIN_PORT,
    MAX_PORT,
    normalizeExtension,
    isExtensionToken,
    parseExtensionList,
    parsePort,
    safeDecode,
    filenameFromPath,
    basenameFromUrl,
    isHttpUrl,
    safeReferrer,
    matchesExtension,
    serverUrl,
    manifestVersion,
  };
})(globalThis);
