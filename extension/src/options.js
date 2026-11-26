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
const statusText = document.getElementById("status-text");
const saveBtn = document.getElementById("save");
const checkBtn = document.getElementById("check");
const testBtn = document.getElementById("test");

function showStatus(ok, text) {
  statusBox.className = `status show ${ok ? "ok" : "bad"}`;
  statusText.textContent = text;
}

function hideStatus() {
  statusBox.className = "status";
}

async function load() {
  const stored = await api.storage.local.get(DEFAULTS);
  const settings = { ...DEFAULTS, ...stored };
  autoBox.checked = Boolean(settings.autoEnabled);
  extensionsBox.value = (settings.extensions || []).join("\n");
  portBox.value = Number(settings.port) || DEFAULTS.port;
}

function parseExtensions() {
  return [...new Set(
    extensionsBox.value
      .split(/[\s,]+/)
      .map((item) => item.trim().toLowerCase().replace(/^\./, ""))
      .filter((item) => /^[a-z0-9]{1,10}$/.test(item)))];
}

function clampPort(value) {
  const port = Math.round(Number(value));
  if (!Number.isFinite(port) || port < 1024 || port > 65535) return DEFAULTS.port;
  return port;
}

async function save() {
  const extensions = parseExtensions();
  await api.storage.local.set({
    autoEnabled: autoBox.checked,
    extensions,
    port: clampPort(portBox.value),
  });
  extensionsBox.value = extensions.join("\n");
  portBox.value = clampPort(portBox.value);
  saveBtn.textContent = "Saved";
  saveBtn.disabled = true;
  setTimeout(() => {
    saveBtn.textContent = "Save";
    saveBtn.disabled = false;
  }, 1600);
}

async function checkConnection() {
  const port = clampPort(portBox.value);
  try {
    const response = await fetch(`http://127.0.0.1:${port}/ping`, {
      headers: { "X-Daryafter-Client": "daryafter-extension/1" },
    });
    if (response.ok) {
      const data = await response.json();
      showStatus(true, `Connected to Daryafter ${data.version || ""}`);
    } else {
      showStatus(false, `The bridge answered but reported HTTP ${response.status}.`);
    }
  } catch (err) {
    showStatus(false, "Could not reach the bridge. Is Daryafter running, and is the "
      + "browser extension enabled in Daryafter's Settings?");
  }
}

async function sendTest() {
  await save();
  testBtn.disabled = true;
  const result = await api.runtime.sendMessage({
    type: "testDownload",
    url: "https://www.example.com/",
  }).catch(() => null);
  testBtn.disabled = false;
  if (!result) {
    showStatus(false, "The background script did not answer. Reload the extension.");
  } else if (result.ok) {
    showStatus(true, "Test link sent. Look at the Daryafter window (and its name dialog, "
      + "if 'Ask for the file name' is on).");
  } else {
    showStatus(false, `The link was refused: ${result.error || "unknown error"}`);
  }
}

saveBtn.addEventListener("click", save);
checkBtn.addEventListener("click", checkConnection);
testBtn.addEventListener("click", sendTest);

load();
