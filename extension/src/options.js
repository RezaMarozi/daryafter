"use strict";

/*
 * Daryafter browser extension - options page.
 *
 * Everything here is driven by the shared DaryafterCommon helpers, so the
 * pop-up and the background script validate and interpret settings the same
 * way. Invalid input is reported next to the field and never silently
 * rewritten or dropped.
 */

const {
  api,
  DEFAULTS,
  CLIENT_HEADER,
  parseExtensionList,
  parsePort,
  manifestVersion,
} = globalThis.DaryafterCommon;

const autoBox = document.getElementById("auto");
const extensionsBox = document.getElementById("extensions");
const portBox = document.getElementById("port");

const extensionsError = document.getElementById("ext-error");
const portError = document.getElementById("port-error");
const extensionCount = document.getElementById("ext-count");

const connectionStatus = document.getElementById("connection-status");
const connectionText = document.getElementById("connection-text");
const checkBtn = document.getElementById("check");
const startBtn = document.getElementById("start");

const saveBtn = document.getElementById("save");
const defaultsBtn = document.getElementById("defaults");
const actionStatus = document.getElementById("action-status");
const actionText = document.getElementById("action-text");
const dirtyNote = document.getElementById("dirty-note");
const bridgeLabel = document.getElementById("bridge-label");
const versionText = document.getElementById("version");

let saved = { ...DEFAULTS };
let checkTimer = null;
let saveFeedbackTimer = null;

/* ---- status helpers ---------------------------------------------------- */

function setStatus(box, textEl, kind, text) {
  box.className = `status show ${kind || ""}`.trim();
  textEl.textContent = text;
}

function clearStatus(box, textEl) {
  box.className = "status";
  textEl.textContent = "";
}

function setFieldError(input, errorEl, message) {
  input.setAttribute("aria-invalid", message ? "true" : "false");
  errorEl.textContent = message || "";
}

/* ---- form state -------------------------------------------------------- */

function formValues() {
  const parsedExtensions = parseExtensionList(extensionsBox.value);
  const parsedPort = parsePort(portBox.value);
  return {
    autoEnabled: autoBox.checked,
    extensions: parsedExtensions.accepted,
    port: parsedPort.ok ? parsedPort.port : null,
    extensionRejected: parsedExtensions.rejected,
    portError: parsedPort.ok ? "" : parsedPort.error,
  };
}

function sameSettings(a, b) {
  return Boolean(a.autoEnabled) === Boolean(b.autoEnabled)
    && Number(a.port) === Number(b.port)
    && (a.extensions || []).join(",") === (b.extensions || []).join(",");
}

function updateDirty() {
  const values = formValues();
  const dirty = !sameSettings(values, saved)
    || values.extensionRejected.length > 0
    || Boolean(values.portError);
  dirtyNote.textContent = dirty ? "Unsaved changes" : "";
  return dirty;
}

function updateExtensionCount() {
  const values = formValues();
  const count = values.extensions.length;
  const rejected = values.extensionRejected.length;
  extensionCount.textContent = rejected
    ? `${count} file type${count === 1 ? "" : "s"} accepted, ${rejected} ignored.`
    : `${count} file type${count === 1 ? "" : "s"}.`;
}

function updateBridgeLabel() {
  const parsed = parsePort(portBox.value);
  const port = parsed.ok ? parsed.port : DEFAULTS.port;
  bridgeLabel.innerHTML = `Bridge <code>127.0.0.1:${port}</code>`;
}

function validateExtensions() {
  const { rejected } = parseExtensionList(extensionsBox.value);
  if (rejected.length) {
    setFieldError(extensionsBox, extensionsError,
      `Not a valid file type: ${rejected.map((item) => `"${item}"`).join(", ")}. `
      + "Use 1-10 letters or digits, for example zip or 7z.");
    return false;
  }
  setFieldError(extensionsBox, extensionsError, "");
  return true;
}

function validatePort() {
  const parsed = parsePort(portBox.value);
  if (!parsed.ok) {
    setFieldError(portBox, portError, parsed.error);
    return false;
  }
  setFieldError(portBox, portError, "");
  return true;
}

function validateAll() {
  const extensionsOk = validateExtensions();
  const portOk = validatePort();
  updateExtensionCount();
  updateDirty();
  return extensionsOk && portOk;
}

function setForm(settings) {
  autoBox.checked = Boolean(settings.autoEnabled);
  extensionsBox.value = (settings.extensions || []).join("\n");
  portBox.value = Number(settings.port) || DEFAULTS.port;
  validateAll();
  updateBridgeLabel();
}

async function load() {
  const stored = await api.storage.local.get(DEFAULTS);
  saved = {
    autoEnabled: Boolean(stored.autoEnabled),
    extensions: Array.isArray(stored.extensions)
      ? stored.extensions.map(String)
      : [...DEFAULTS.extensions],
    port: Number(stored.port) || DEFAULTS.port,
  };
  setForm(saved);
  versionText.textContent = manifestVersion() ? `v${manifestVersion()}` : "";
  checkConnection({ quiet: true });
}

/* ---- persistence ------------------------------------------------------- */

async function persist(settings, message) {
  await api.storage.local.set(settings);
  saved = {
    autoEnabled: Boolean(settings.autoEnabled),
    extensions: [...settings.extensions],
    port: settings.port,
  };
  updateDirty();
  clearTimeout(saveFeedbackTimer);
  saveBtn.textContent = "Saved";
  saveFeedbackTimer = setTimeout(() => {
    saveBtn.textContent = "Save";
  }, 1200);
  setStatus(actionStatus, actionText, "ok", message);
  checkConnection({ quiet: true });
}

async function save() {
  if (!validateAll()) {
    setStatus(actionStatus, actionText, "bad",
      "Fix the highlighted fields before saving.");
    return;
  }
  const values = formValues();
  try {
    await persist({
      autoEnabled: values.autoEnabled,
      extensions: values.extensions,
      port: values.port,
    }, `Saved. ${values.extensions.length} file type`
      + `${values.extensions.length === 1 ? "" : "s"} auto-download.`);
  } catch (err) {
    setStatus(actionStatus, actionText, "bad", `Could not save: ${err}`);
  }
}

async function restoreDefaults() {
  autoBox.checked = DEFAULTS.autoEnabled;
  extensionsBox.value = DEFAULTS.extensions.join("\n");
  portBox.value = DEFAULTS.port;
  validateAll();
  updateBridgeLabel();
  try {
    await persist({
      autoEnabled: DEFAULTS.autoEnabled,
      extensions: [...DEFAULTS.extensions],
      port: DEFAULTS.port,
    }, "Defaults restored and saved.");
  } catch (err) {
    setStatus(actionStatus, actionText, "bad", `Could not restore defaults: ${err}`);
  }
}

/* ---- connection -------------------------------------------------------- */

function setConnection(kind, text, showStart) {
  setStatus(connectionStatus, connectionText, kind, text);
  startBtn.hidden = !showStart;
}

async function checkConnection({ quiet = false } = {}) {
  const parsed = parsePort(portBox.value);
  if (!parsed.ok) {
    setConnection("warn", "Enter a valid port to test the connection.", false);
    return;
  }
  if (!quiet) {
    setConnection("", "Checking\u2026", false);
    checkBtn.disabled = true;
  }
  try {
    const response = await fetch(`http://127.0.0.1:${parsed.port}/ping`, {
      cache: "no-store",
      headers: CLIENT_HEADER,
    });
    if (!response.ok) {
      setConnection("warn",
        `The bridge answered with HTTP ${response.status}.`, false);
      return;
    }
    const data = await response.json().catch(() => ({}));
    setConnection("ok",
      `Connected to Daryafter${data.version ? ` ${data.version}` : ""}.`, false);
  } catch (err) {
    setConnection("bad",
      "Daryafter is not reachable. Start it, then check again.", true);
  } finally {
    if (!quiet) checkBtn.disabled = false;
  }
}

function scheduleConnectionCheck() {
  clearTimeout(checkTimer);
  checkTimer = setTimeout(() => {
    if (parsePort(portBox.value).ok) checkConnection({ quiet: true });
  }, 350);
}

async function startDaryafter() {
  startBtn.disabled = true;
  const original = startBtn.textContent;
  startBtn.textContent = "Starting\u2026";
  setConnection("", "Starting Daryafter\u2026", true);
  try {
    const reply = await api.runtime.sendMessage({ type: "startDaryafter" });
    if (reply && reply.running) {
      await checkConnection({ quiet: true });
    } else {
      setConnection("bad", reply && reply.error
        ? `Could not start: ${reply.error}`
        : "Still not running \u2014 is the native host installed?", true);
    }
  } catch (err) {
    setConnection("bad", `Could not start: ${err}`, true);
  } finally {
    startBtn.disabled = false;
    startBtn.textContent = original;
  }
}

/* ---- wiring ------------------------------------------------------------ */

autoBox.addEventListener("change", updateDirty);
extensionsBox.addEventListener("input", () => {
  validateExtensions();
  updateExtensionCount();
  updateDirty();
});
extensionsBox.addEventListener("blur", validateExtensions);
portBox.addEventListener("input", () => {
  validatePort();
  updateBridgeLabel();
  updateDirty();
  scheduleConnectionCheck();
});
portBox.addEventListener("blur", validatePort);

saveBtn.addEventListener("click", save);
defaultsBtn.addEventListener("click", restoreDefaults);
checkBtn.addEventListener("click", () => checkConnection());
startBtn.addEventListener("click", startDaryafter);

document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
    event.preventDefault();
    save();
  }
});

api.storage.onChanged?.addListener(async (changes, area) => {
  if (area !== "local") return;
  if (!changes.autoEnabled && !changes.extensions && !changes.port) return;
  const stored = await api.storage.local.get(DEFAULTS);
  saved = {
    autoEnabled: Boolean(stored.autoEnabled),
    extensions: Array.isArray(stored.extensions)
      ? stored.extensions.map(String)
      : [...DEFAULTS.extensions],
    port: Number(stored.port) || DEFAULTS.port,
  };
  // Reflect changes made from the pop-up without discarding text the user
  // is still editing here.
  if (changes.autoEnabled) {
    autoBox.checked = saved.autoEnabled;
  }
  updateDirty();
});

load();
