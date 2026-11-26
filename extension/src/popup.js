"use strict";

const {
  api,
  DEFAULTS,
  manifestVersion,
} = globalThis.DaryafterCommon;

const statusBox = document.getElementById("status");
const statusText = document.getElementById("status-text");
const autoBox = document.getElementById("auto");
const startBtn = document.getElementById("start-btn");
const bridgeText = document.getElementById("bridge");
const saveNote = document.getElementById("save-note");
const versionText = document.getElementById("version");

function setStatus(kind, text) {
  statusBox.className = `status show ${kind || ""}`.trim();
  statusText.textContent = text;
}

function setNote(text) {
  saveNote.textContent = text || "";
  if (text) {
    setTimeout(() => {
      if (saveNote.textContent === text) saveNote.textContent = "";
    }, 1800);
  }
}

async function refresh() {
  const settings = await api.storage.local.get(DEFAULTS);
  autoBox.checked = Boolean(settings.autoEnabled);
  bridgeText.textContent = `127.0.0.1:${settings.port || DEFAULTS.port}`;

  const reply = await api.runtime.sendMessage({ type: "ping" }).catch(() => null);
  if (reply && reply.running) {
    setStatus("ok", "Connected to Daryafter");
    startBtn.hidden = true;
  } else {
    setStatus("bad", "Daryafter is not running");
    startBtn.hidden = false;
  }
}

autoBox.addEventListener("change", async () => {
  try {
    await api.storage.local.set({ autoEnabled: autoBox.checked });
    setNote("Saved");
  } catch (err) {
    setNote("Could not save");
  }
});

startBtn.addEventListener("click", async () => {
  startBtn.disabled = true;
  const original = startBtn.textContent;
  startBtn.textContent = "Starting\u2026";
  const reply = await api.runtime.sendMessage({ type: "startDaryafter" }).catch(() => null);
  startBtn.disabled = false;
  startBtn.textContent = original;
  if (reply && reply.running) {
    setStatus("ok", "Connected to Daryafter");
    startBtn.hidden = true;
  } else {
    setStatus("bad", reply && reply.error
      ? `Could not start: ${reply.error}`
      : "Still not running \u2014 is the native host installed?");
  }
});

document.getElementById("options-link").addEventListener("click", () => {
  api.runtime.openOptionsPage().catch(() => {
    window.open(api.runtime.getURL("options.html"), "_blank");
  });
});

api.storage.onChanged?.addListener((changes, area) => {
  if (area === "local" && (changes.autoEnabled || changes.port)) refresh();
});

versionText.textContent = manifestVersion() ? `v${manifestVersion()}` : "";
refresh();
