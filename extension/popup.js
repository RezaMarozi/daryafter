"use strict";

const api = globalThis.browser ?? globalThis.chrome;

const statusBox = document.getElementById("status");
const statusText = document.getElementById("status-text");
const autoBox = document.getElementById("auto");

document.getElementById("options-link").addEventListener("click", (event) => {
  event.preventDefault();
  api.runtime.openOptionsPage();
});

autoBox.addEventListener("change", async () => {
  await api.storage.local.set({ autoEnabled: autoBox.checked });
});

async function refresh() {
  const stored = await api.storage.local.get({ autoEnabled: false });
  autoBox.checked = Boolean(stored.autoEnabled);
  const reply = await api.runtime.sendMessage({ type: "ping" }).catch(() => null);
  if (reply && reply.running) {
    statusBox.classList.add("ok");
    statusText.textContent = "Connected to Daryafter";
  } else {
    statusBox.classList.add("bad");
    statusText.textContent = "Daryafter is not running";
  }
}

refresh();
