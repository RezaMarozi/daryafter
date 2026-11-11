"use strict";

const api = globalThis.browser ?? globalThis.chrome;

const DEFAULTS = {
  autoEnabled: false,
  port: 27240,
  extensions: [
    "7z", "apk", "avi", "bin", "bz2", "cab", "crx", "deb", "dmg", "epub",
    "exe", "flac", "gz", "img", "iso", "mkv", "mov", "mp3", "mp4", "msi",
    "ogg", "pkg", "psd", "rar", "rpm", "tar", "wav", "webm", "xz", "zst", "zip",
  ],
};

const autoBox = document.getElementById("auto");
const extensionsBox = document.getElementById("extensions");
const portBox = document.getElementById("port");
const statusBox = document.getElementById("status");

async function load() {
  const stored = await api.storage.local.get(DEFAULTS);
  const settings = { ...DEFAULTS, ...stored };
  autoBox.checked = Boolean(settings.autoEnabled);
  extensionsBox.value = (settings.extensions || []).join("\n");
  portBox.value = Number(settings.port) || DEFAULTS.port;
}

async function save() {
  const extensions = extensionsBox.value
    .split(/[\s,]+/)
    .map((item) => item.trim().toLowerCase().replace(/^\./, ""))
    .filter((item) => /^[a-z0-9]{1,10}$/.test(item));
  const unique = [...new Set(extensions)];
  await api.storage.local.set({
    autoEnabled: autoBox.checked,
    extensions: unique,
    port: clampPort(portBox.value),
  });
  extensionsBox.value = unique.join("\n");
  statusBox.className = "status ok";
  statusBox.textContent = "Saved.";
}

function clampPort(value) {
  const port = Math.round(Number(value));
  if (!Number.isFinite(port) || port < 1024 || port > 65535) return DEFAULTS.port;
  return port;
}

function setStatus(ok, text) {
  statusBox.className = `status ${ok ? "ok" : "bad"}`;
  statusBox.textContent = text;
}

async function checkConnection() {
  const port = clampPort(portBox.value);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/ping`, {
      headers: { "X-Daryafter-Client": "daryafter-extension/1" },
    });
    if (response.ok) {
      const data = await response.json();
      setStatus(true, `Connected: ${data.app || "Daryafter"} ${data.version || ""}`);
    } else {
      setStatus(false, `The bridge answered but reported HTTP ${response.status}.`);
    }
  } catch (err) {
    setStatus(false, "Could not reach the bridge. Is Daryafter running, and is the "
      + "browser extension enabled in Daryafter's Settings?");
  }
}

async function sendTest() {
  await save();
  const result = await api.runtime.sendMessage({
    type: "testDownload",
    url: "https://www.example.com/",
  }).catch(() => null);
  if (!result) setStatus(false, "The background script did not answer. Reload the extension.");
  else if (result.ok) setStatus(true, "Test link sent. Look at the Daryafter window "
    + "(and its name dialog, if 'Ask for the file name' is on).");
}

document.getElementById("check").addEventListener("click", checkConnection);
document.getElementById("test").addEventListener("click", sendTest);
document.getElementById("save").addEventListener("click", save);

load();
