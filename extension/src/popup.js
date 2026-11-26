"use strict";

const api = globalThis.browser ?? globalThis.chrome;

const statusBox = document.getElementById("status");
const statusText = document.getElementById("status-text");
const autoBox = document.getElementById("auto");
const startBtn = document.getElementById("start-btn");

document.getElementById("options-link").addEventListener("click", (event) => {
  event.preventDefault();
  api.runtime.openOptionsPage();
});

autoBox.addEventListener("change", async () => {
  await api.storage.local.set({ autoEnabled: autoBox.checked });
});

startBtn.addEventListener("click", async () => {
  startBtn.disabled = true;
  startBtn.textContent = "Starting...";
  const reply = await api.runtime.sendMessage({ type: "startDaryafter" }).catch(() => null);
  startBtn.disabled = false;
  startBtn.textContent = "Start Daryafter";
  statusBox.classList.remove("ok", "bad");
  if (reply && reply.running) {
    statusBox.classList.add("ok");
    statusText.textContent = "Connected to Daryafter";
    startBtn.hidden = true;
  } else {
    statusBox.classList.add("bad");
    statusText.textContent = reply && reply.error ? `Could not start: ${reply.error}`
      : "Still not running - is the native host installed?";
  }
});

async function refresh() {
  const stored = await api.storage.local.get({ autoEnabled: false });
  autoBox.checked = Boolean(stored.autoEnabled);
  const reply = await api.runtime.sendMessage({ type: "ping" }).catch(() => null);
  statusBox.classList.remove("ok", "bad");
  if (reply && reply.running) {
    statusBox.classList.add("ok");
    statusText.textContent = "Connected to Daryafter";
    startBtn.hidden = true;
  } else {
    statusBox.classList.add("bad");
    statusText.textContent = "Daryafter is not running";
    startBtn.hidden = false;
  }
}

refresh();
