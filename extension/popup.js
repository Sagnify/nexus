"use strict";

// ── Refs ──────────────────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

const statusDot    = $("statusDot");
const statusLabel  = $("statusLabel");
const statusMeta   = $("statusMeta");
const pingVal      = $("pingVal");
const syncVal      = $("syncVal");
const faviconBox   = $("faviconBox");
const tabName      = $("tabName");
const tabHost      = $("tabHost");
const automPanel   = $("automPanel");
const stepCur      = $("stepCur");
const stepTot      = $("stepTot");
const elapsed      = $("elapsed");
const statePill    = $("statePill");
const progressFill = $("progressFill");
const actionLine   = $("actionLine");
const statsSection = $("statsSection");
const sSteps       = $("sSteps");
const sValid       = $("sValid");
const sRetry       = $("sRetry");
const controls     = $("controls");
const btnResume    = $("btnResume");
const btnPause     = $("btnPause");
const btnStop      = $("btnStop");
const idleRow      = $("idleRow");
const logSection   = $("logSection");
const logList      = $("logList");
const logCounter   = $("logCounter");
const reconnectBtn = $("reconnectBtn");
const footerDot    = $("footerDot");
const footerText   = $("footerText");

// ── State ─────────────────────────────────────────────────────────────────────
let startEpoch = null;
let elapsedTick = null;
let logItems = [];
const MAX_LOG = 30;

// ── Utilities ─────────────────────────────────────────────────────────────────
function pad(n) { return String(Math.floor(n)).padStart(2, "0"); }

function formatElapsed(ms) {
  const s = Math.floor(ms / 1000);
  return `${pad(Math.floor(s / 60))}:${pad(s % 60)}`;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); }
  catch { return ""; }
}

function nowTime() {
  const d = new Date();
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function esc(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

// ── Connection ────────────────────────────────────────────────────────────────
function applyConnection(connected, pingMs) {
  if (connected) {
    statusDot.className = "dot online";
    statusLabel.textContent = "Connected";
    footerDot.className = "footer-dot online";
    footerText.textContent = "Backend active";
    statusMeta.style.display = "flex";
    pingVal.textContent = pingMs != null ? `${pingMs}ms` : "—";
    syncVal.textContent = nowTime();
  } else {
    statusDot.className = "dot offline";
    statusLabel.textContent = "Offline";
    footerDot.className = "footer-dot";
    footerText.textContent = "Backend unreachable";
    statusMeta.style.display = "none";
  }
}

function checkStatus() {
  const t0 = Date.now();
  chrome.runtime.sendMessage({ action: "getStatus" }, (res) => {
    if (chrome.runtime.lastError || !res) {
      chrome.storage.local.get(["nexusStatus"], (d) => {
        applyConnection(d.nexusStatus === "connected");
      });
      return;
    }
    applyConnection(res.connected, res.connected ? (Date.now() - t0) : null);
  });
}

// ── Tab ───────────────────────────────────────────────────────────────────────
async function loadTab() {
  try {
    const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
    const tab = tabs && tabs[0];
    if (!tab) { tabName.textContent = "No active tab"; return; }

    tabName.textContent = tab.title || tab.url || "Untitled";
    const host = hostOf(tab.url || "");
    tabHost.textContent = host;

    if (host) {
      const img = document.createElement("img");
      img.src = `https://www.google.com/s2/favicons?sz=32&domain=${host}`;
      img.onerror = () => { faviconBox.innerHTML = '<div class="placeholder"></div>'; };
      img.onload  = () => { faviconBox.innerHTML = ""; faviconBox.appendChild(img); };
    }
  } catch {
    tabName.textContent = "Unavailable";
  }
}

// ── Automation state ──────────────────────────────────────────────────────────
function show(el, visible) {
  el.style.display = visible ? "" : "none";
}

function applyAutomation(state, data = {}) {
  const isActive = state === "running" || state === "paused";

  show(automPanel,   isActive);
  show(statsSection, isActive);
  show(controls,     false);  // re-shown below if active
  show(idleRow,      !isActive);
  logSection.style.display = logItems.length > 0 ? "" : "none";

  if (!isActive) {
    stopElapsed();
    return;
  }

  // State pill
  if (state === "paused") {
    statePill.className = "state-pill paused";
    statePill.textContent = "Paused";
  } else {
    statePill.className = "state-pill running";
    statePill.textContent = "Running";
  }

  // Steps
  const cur = data.step  ?? 0;
  const tot = data.total ?? 0;
  stepCur.textContent = cur;
  stepTot.textContent = tot > 0 ? tot : "—";
  progressFill.style.width = tot > 0 ? `${Math.min(100, Math.round((cur / tot) * 100))}%` : "0%";

  // Action
  actionLine.textContent = data.action || "Working";

  // Stats
  sSteps.textContent = data.steps_done ?? cur;
  sValid.textContent = data.validations
    ? `${data.validations.passed}/${data.validations.total}`
    : "—";
  sRetry.textContent = data.retries ?? 0;

  // Controls
  controls.style.display = "flex";
  btnResume.disabled = state === "running";
  btnPause.disabled  = state === "paused";
  btnStop.disabled   = false;

  // Elapsed
  if (data.started_at && !elapsedTick) {
    startEpoch = data.started_at;
    startElapsed();
  }
}

function startElapsed() {
  stopElapsed();
  if (!startEpoch) return;
  elapsedTick = setInterval(() => {
    elapsed.textContent = formatElapsed(Date.now() - startEpoch);
  }, 1000);
}

function stopElapsed() {
  if (elapsedTick) { clearInterval(elapsedTick); elapsedTick = null; }
  elapsed.textContent = "00:00";
}

// ── Log ───────────────────────────────────────────────────────────────────────
function renderLog() {
  logList.innerHTML = "";
  for (const item of logItems) {
    const row = document.createElement("div");
    row.className = "log-row";
    row.innerHTML =
      `<span class="log-badge ${item.type}">${item.type.toUpperCase()}</span>` +
      `<span class="log-text">${esc(item.msg)}</span>` +
      `<span class="log-ts">${item.time}</span>`;
    logList.appendChild(row);
  }
  logCounter.textContent = logItems.length;
  logSection.style.display = logItems.length > 0 ? "" : "none";
}

function addLog(type, msg) {
  logItems.unshift({ type, msg, time: nowTime() });
  if (logItems.length > MAX_LOG) logItems.pop();
  renderLog();
}

// ── Storage listener ──────────────────────────────────────────────────────────
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;

  if (changes.nexusStatus) {
    applyConnection(changes.nexusStatus.newValue === "connected");
  }

  if (changes.nexusAutomationState) {
    const s = changes.nexusAutomationState.newValue;
    if (!s || s.state === "stopped" || s.state === "idle") {
      applyAutomation(null);
      stopElapsed();
    } else {
      applyAutomation(s.state, s);
    }
  }

  if (changes.nexusStepLog) {
    const logs = changes.nexusStepLog.newValue;
    if (Array.isArray(logs) && logs.length > 0) {
      const l = logs[0];
      addLog(l.type || "info", l.msg || "");
    }
  }
});

// ── Controls ──────────────────────────────────────────────────────────────────
function sendControl(action) {
  chrome.runtime.sendMessage({ action }, () => {
    if (chrome.runtime.lastError) addLog("err", `Failed: ${action}`);
  });
}

btnResume.addEventListener("click", () => {
  sendControl("pause_resume");
  addLog("info", "Resumed");
  // Optimistic UI
  chrome.storage.local.get(["nexusAutomationState"], (d) => {
    const s = d.nexusAutomationState || {};
    applyAutomation("running", s);
  });
});

btnPause.addEventListener("click", () => {
  sendControl("pause_automation");
  addLog("warn", "Paused");
  chrome.storage.local.get(["nexusAutomationState"], (d) => {
    const s = d.nexusAutomationState || {};
    applyAutomation("paused", s);
  });
});

btnStop.addEventListener("click", () => {
  sendControl("stop_automation");
  addLog("err", "Stopped by user");
  setTimeout(() => {
    applyAutomation(null);
    chrome.storage.local.remove(["nexusAutomationState"]);
  }, 600);
});

// ── Reconnect ─────────────────────────────────────────────────────────────────
reconnectBtn.addEventListener("click", () => {
  reconnectBtn.textContent = "Connecting…";
  reconnectBtn.disabled = true;
  chrome.runtime.sendMessage({ action: "reconnect" }, (res) => {
    setTimeout(() => {
      reconnectBtn.textContent = "Reconnect";
      reconnectBtn.disabled = false;
      applyConnection(res ? res.connected : false);
    }, 500);
  });
});

// ── Init ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  checkStatus();
  loadTab();

  // Load persisted state
  chrome.storage.local.get(["nexusAutomationState", "nexusStepLog"], (d) => {
    if (d.nexusStepLog && Array.isArray(d.nexusStepLog)) {
      logItems = d.nexusStepLog.slice(0, MAX_LOG);
    }

    const s = d.nexusAutomationState;
    if (s && (s.state === "running" || s.state === "paused")) {
      applyAutomation(s.state, s);
    } else {
      applyAutomation(null);
    }

    renderLog();
  });

  const poll = setInterval(checkStatus, 4000);
  window.addEventListener("unload", () => clearInterval(poll));
});
