/**
 * NEXUS Chrome Companion - Background Service Worker
 * Manages WebSocket communication with local NEXUS backend and dispatches tab actions.
 */

const WS_URL = "ws://127.0.0.1:8000/ws/extension";
let socket = null;
let isConnecting = false;
let reconnectTimer = null;

let isAutomationRunning = false;
let activeAutomationTabId = null;
const automationSessionTabIds = new Set();

let isTeachModeRunning = false;
let activeTeachModeTabId = null;
let teachSessionId = null;
let currentTeachPrompt = "";
let teachStartedAt = Date.now();
let isTeachPaused = false;
let recordedActionsHistory = [];

// Listen for demonstration events from content script
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (!request) return;
    if (request.type === "teach_event" && isTeachModeRunning) {
        if (request.action_summary) {
            recordedActionsHistory.push(request.action_summary);
        }
        wsSend({
            type: "teach_event",
            session_id: teachSessionId,
            event: request.payload
        });
    } else if (request.type === "teach_action") {
        const sId = request.session_id || teachSessionId;
        if (request.action === "pause") isTeachPaused = true;
        if (request.action === "resume") isTeachPaused = false;
        wsSend({
            type: "teach_action",
            action: request.action,
            session_id: sId
        });
        if (request.action === "finish") {
            // ⚡ Instant 0ms wakeup of Spotlight window
            fetch("http://127.0.0.1:8765/show-spotlight", { method: "POST" }).catch(() => {});
            // Direct loopback HTTP call to guarantee backend marks session completed in 0ms
            fetch("http://127.0.0.1:8000/api/skills/teach/stop-direct", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ session_id: sId })
            }).catch(() => {});
        }
        if (request.action === "finish" || request.action === "discard") {
            isTeachModeRunning = false;
            activeTeachModeTabId = null;
            teachSessionId = null;
            currentTeachPrompt = "";
            recordedActionsHistory = [];
            isTeachPaused = false;
        }
    }
});

// Maintain continuous worker execution while browser tabs are open
if (chrome.runtime && chrome.runtime.onConnect) {
    chrome.runtime.onConnect.addListener((port) => {
        if (port.name === "nexus-keepalive") {
            port.onMessage?.addListener(() => {});
        }
    });
}


// Clean reset any leftover automation state on extension load/reload
// Also expire any stale "running" state older than 10 minutes
chrome.storage.local.get(["nexusAutomationState"], (d) => {
    const st = d?.nexusAutomationState;
    const isStale = !st || st.state === "stopped" ||
        (st.state === "running" && st.started_at && (Date.now() - st.started_at) > 10 * 60 * 1000);
    if (isStale) {
        chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
        deactivateOverlayOnOtherTabs(null);
    }
});

/**
 * Dispatches automation_stop to every tab except keepTabId to ensure
 * only one single tab displays the automation overlay and pill.
 */
async function deactivateOverlayOnOtherTabs(keepTabId) {
    try {
        const allTabs = await chrome.tabs.query({});
        for (const t of allTabs) {
            if (t.id && t.id !== keepTabId) {
                chrome.tabs.sendMessage(t.id, { action: "automation_stop" }).catch(() => {});
            }
        }
    } catch (_) {}
}

/**
 * Pushes the current automation overlay state to the active automation tab.
 * Injects content script defensively if needed so the overlay immediately appears.
 */
async function syncOverlayToActiveTab(tabId) {
    if (!tabId || !isAutomationRunning) return;
    try {
        const tab = await chrome.tabs.get(tabId);
        const url = tab.url || tab.pendingUrl || "";
        if (!url || url.startsWith("chrome://") || url.startsWith("chrome-extension://") || url.startsWith("edge://") || url.startsWith("about:")) {
            return;
        }

        await deactivateOverlayOnOtherTabs(tabId);

        chrome.storage.local.get(["nexusAutomationState"], async (d) => {
            const st = d?.nexusAutomationState;
            if (st && (st.state === "running" || st.state === "paused")) {
                const payload = {
                    task: st.action || "Automating...",
                    step: st.action || "",
                    step_index: st.step || 0,
                    total_steps: st.total || 0,
                    state: st.state,
                    started_at: st.started_at
                };
                try {
                    await chrome.tabs.sendMessage(tabId, { action: "automation_start", payload });
                    if (st.state === "paused") {
                        await chrome.tabs.sendMessage(tabId, { action: "automation_pause" });
                    }
                } catch (_) {
                    try {
                        await chrome.scripting.executeScript({
                            target: { tabId: tabId },
                            files: ["content.js"]
                        });
                        await new Promise(r => setTimeout(r, 200));
                        await chrome.tabs.sendMessage(tabId, { action: "automation_start", payload });
                        if (st.state === "paused") {
                            await chrome.tabs.sendMessage(tabId, { action: "automation_pause" });
                        }
                    } catch (_) {}
                }
            }
        });
    } catch (_) {}
}

// ── Native CDP Mouse Input via chrome.debugger ──────────────────────────────
// Dispatches authentic, browser-level isTrusted: true mouse events
const attachedDebuggers = new Set();

async function attachDebuggerIfNeeded(tabId) {
    if (!chrome.debugger || !tabId) return false;
    if (attachedDebuggers.has(tabId)) return true;
    try {
        await chrome.debugger.attach({ tabId: tabId }, "1.3");
        attachedDebuggers.add(tabId);
        return true;
    } catch (e) {
        if (e?.message && e.message.includes("Already attached")) {
            attachedDebuggers.add(tabId);
            return true;
        }
        console.debug("[NEXUS] Debugger attach info:", e?.message);
        return false;
    }
}

async function detachDebugger(tabId) {
    if (!chrome.debugger || !tabId || !attachedDebuggers.has(tabId)) return;
    try {
        await chrome.debugger.detach({ tabId: tabId });
    } catch (_) {}
    attachedDebuggers.delete(tabId);
}

if (chrome.debugger && chrome.debugger.onDetach) {
    chrome.debugger.onDetach.addListener((source) => {
        if (source && source.tabId) {
            attachedDebuggers.delete(source.tabId);
        }
    });
}

async function dispatchNativeMouseClick(tabId, x, y) {
    if (!chrome.debugger || !tabId) return false;
    const attached = await attachDebuggerIfNeeded(tabId);
    if (!attached) return false;
    try {
        const roundX = Math.round(x);
        const roundY = Math.round(y);
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
            type: "mouseMoved",
            x: roundX,
            y: roundY
        });
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
            type: "mousePressed",
            x: roundX,
            y: roundY,
            button: "left",
            clickCount: 1
        });
        await new Promise(r => setTimeout(r, 45));
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
            type: "mouseReleased",
            x: roundX,
            y: roundY,
            button: "left",
            clickCount: 1
        });
        return true;
    } catch (e) {
        console.debug("[NEXUS] Native mouse click dispatch:", e?.message);
        return false;
    }
}

async function dispatchNativeMouseMove(tabId, x, y) {
    if (!chrome.debugger || !tabId) return false;
    const attached = await attachDebuggerIfNeeded(tabId);
    if (!attached) return false;
    try {
        await chrome.debugger.sendCommand({ tabId }, "Input.dispatchMouseEvent", {
            type: "mouseMoved",
            x: Math.round(x),
            y: Math.round(y)
        });
        return true;
    } catch (e) {
        return false;
    }
}

// Listen for messages from popup and content scripts
chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === "getStatus") {
        const isConnected = socket && socket.readyState === WebSocket.OPEN;
        sendResponse({ connected: isConnected });
        return true;
    }
    if (request.action === "reconnect") {
        connectToNexus();
        setTimeout(() => {
            const isConnected = socket && socket.readyState === WebSocket.OPEN;
            sendResponse({ connected: isConnected });
        }, 300);
        return true;
    }
    // Control actions → forward to backend via WebSocket or background fetch (safe from PNA restrictions)
    if (request.action === "pause_automation") {
        wsSend({ type: "pause" });
        fetch("http://127.0.0.1:8000/api/nexus/pause", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
        sendResponse({ sent: true });
        return true;
    }
    if (request.action === "pause_resume") {
        wsSend({ type: "resume" });
        fetch("http://127.0.0.1:8000/api/nexus/resume", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
        sendResponse({ sent: true });
        return true;
    }
    if (request.action === "stop_automation") {
        isAutomationRunning = false;
        activeAutomationTabId = null;
        automationSessionTabIds.clear();
        wsSend({ type: "cancel" });
        fetch("http://127.0.0.1:8000/api/nexus/cancel", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }).catch(() => {});
        chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
        deactivateOverlayOnOtherTabs(null);
        sendResponse({ sent: true });
        return true;
    }
    if (request.action === "dispatch_native_click") {
        const tabId = sender.tab?.id || activeAutomationTabId;
        if (tabId && typeof request.x === "number" && typeof request.y === "number") {
            dispatchNativeMouseClick(tabId, request.x, request.y).then(success => {
                sendResponse({ success });
            });
            return true;
        }
        sendResponse({ success: false });
        return true;
    }
    if (request.action === "dispatch_native_move") {
        const tabId = sender.tab?.id || activeAutomationTabId;
        if (tabId && typeof request.x === "number" && typeof request.y === "number") {
            dispatchNativeMouseMove(tabId, request.x, request.y).then(success => {
                sendResponse({ success });
            });
            return true;
        }
        sendResponse({ success: false });
        return true;
    }
    if (request.action === "submit_user_input") {
        wsSend({ type: "input", value: request.value, task_id: request.task_id });
        fetch("http://127.0.0.1:8000/api/nexus/input", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ value: request.value, task_id: request.task_id })
        }).catch(() => {});
        sendResponse({ sent: true });
        return true;
    }
    if (request.action === "check_tab_active_automation") {
        // If automation is running and this sender tab is the active tab or no active tab was claimed yet
        if (isAutomationRunning && sender.tab?.id && !activeAutomationTabId) {
            activeAutomationTabId = sender.tab.id;
        }

        const isCurrentActiveTab = Boolean(
            isAutomationRunning &&
            sender.tab &&
            activeAutomationTabId &&
            activeAutomationTabId === sender.tab.id
        );

        chrome.storage.local.get(["nexusAutomationState"], (d) => {
            const st = d?.nexusAutomationState?.state;
            const startedAt = d?.nexusAutomationState?.started_at || 0;
            // Auto-expire: if state says running but >10 min old with no live WS, treat as stopped
            const isStale = (st === "running") && (Date.now() - startedAt) > 10 * 60 * 1000;
            const isRunning = isAutomationRunning && (st === "running" || st === "paused") && !isStale;

            if (isStale) {
                // Background-clear the stale state so next check is clean
                isAutomationRunning = false;
                activeAutomationTabId = null;
                chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
                deactivateOverlayOnOtherTabs(null);
            }

            sendResponse({
                is_active: isCurrentActiveTab && isRunning,
                active_tab_id: isRunning ? activeAutomationTabId : null,
                automation_state: isRunning ? d?.nexusAutomationState : null,
            });
        });
        return true;
    }
});

// When a tab is closed, gracefully switch to a remaining tab rather than crashing the automation
chrome.tabs.onRemoved.addListener(async (tabId) => {
    automationSessionTabIds.delete(tabId);
    if (tabId === activeAutomationTabId) {
        activeAutomationTabId = null;
        try {
            const nextTab = await getFocusedOrActiveTab();
            if (nextTab && nextTab.id) {
                const nextUrl = nextTab.url || nextTab.pendingUrl || "";
                if (!nextUrl.startsWith("chrome://") && !nextUrl.startsWith("edge://")) {
                    activeAutomationTabId = nextTab.id;
                    if (isAutomationRunning) {
                        await syncOverlayToActiveTab(nextTab.id);
                    }
                    return;
                }
            }
            const allTabs = await chrome.tabs.query({});
            const realTab = allTabs.find(t => t.id && t.url && (t.url.startsWith("http://") || t.url.startsWith("https://")));
            if (realTab && realTab.id) {
                activeAutomationTabId = realTab.id;
                await chrome.tabs.update(realTab.id, { active: true }).catch(() => {});
                if (isAutomationRunning) {
                    await syncOverlayToActiveTab(realTab.id);
                }
                return;
            }
        } catch (_) {}

        // Only clear state if no tabs remain
        isAutomationRunning = false;
        chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
        deactivateOverlayOnOtherTabs(null);
    }
});

function connectToNexus() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return;
    }
    if (isConnecting) return;
    isConnecting = true;

    try {
        socket = new WebSocket(WS_URL);

        socket.onopen = () => {
            console.log("[NEXUS Extension] Connected to NEXUS Backend via WebSocket 🟢");
            isConnecting = false;
            chrome.storage.local.set({ nexusStatus: "connected", lastConnected: Date.now() });
            // Send client registration
            socket.send(JSON.stringify({
                type: "register",
                client: "chrome_extension",
                version: "2.0.0"
            }));
        };

        socket.onmessage = async (event) => {
            let message = null;
            try {
                message = JSON.parse(event.data);
                const { id, action, payload } = message;
                const result = await handleCommand(action, payload || {});
                wsSend({
                    id: id,
                    success: true,
                    data: result
                });
            } catch (err) {
                console.error("[NEXUS Extension] Command error:", err);
                wsSend({
                    id: message ? message.id : null,
                    success: false,
                    error: err?.message || String(err)
                });
            }
        };

        socket.onclose = () => {
            console.log("[NEXUS Extension] Disconnected from NEXUS Backend 🔴. Retrying...");
            isConnecting = false;
            socket = null;
            isAutomationRunning = false;
            activeAutomationTabId = null;
            automationSessionTabIds.clear();
            chrome.storage.local.set({ nexusStatus: "disconnected", nexusAutomationState: { state: "stopped" } });
            deactivateOverlayOnOtherTabs(null);
            scheduleReconnect();
        };

        socket.onerror = (err) => {
            console.debug("[NEXUS Extension] WebSocket connection error, retrying in background...");
            isConnecting = false;
        };
    } catch (e) {
        isConnecting = false;
        scheduleReconnect();
    }
}

function scheduleReconnect() {
    if (reconnectTimer) clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(() => {
        connectToNexus();
    }, 1000);
}

/** Safe WebSocket send — silently drops if socket isn't open. */
function wsSend(obj) {
    try {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(obj));
        }
    } catch (_) {}
}

/** Prepend a log entry to chrome.storage.local so the popup can show it. */
const MAX_LOG_STORAGE = 30;
function pushStepLog(type, msg) {
    try {
        chrome.storage.local.get(["nexusStepLog"], (d) => {
            const logs = Array.isArray(d.nexusStepLog) ? d.nexusStepLog : [];
            const entry = { type, msg, time: new Date().toLocaleTimeString("en-GB", { hour12: false }) };
            const updated = [entry, ...logs].slice(0, MAX_LOG_STORAGE);
            chrome.storage.local.set({ nexusStepLog: updated });
        });
    } catch (_) {}
}


async function getFocusedOrActiveTab() {
    try {
        const win = await chrome.windows.getLastFocused({ populate: true, windowTypes: ['normal'] });
        if (win && win.tabs) {
            const active = win.tabs.find(t => t.active);
            if (active) return active;
        }
    } catch (_) {}
    try {
        const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
        if (tabs && tabs.length > 0) return tabs[0];
        const anyTabs = await chrome.tabs.query({ active: true });
        return anyTabs[0] || null;
    } catch (_) {
        return null;
    }
}

async function getActiveTab() {
    return getFocusedOrActiveTab();
}

function isRecordableTeachTab(tab) {
    const url = tab?.url || tab?.pendingUrl || "";
    return url.startsWith("http://") || url.startsWith("https://");
}

/**
 * Returns the target tab for browser automation.
 * Operates sequentially and gracefully focuses the right tab without locking to stale/wrong tabs.
 */
async function getTargetAutomationTab(preferredTabId = null) {
    const allTabs = await chrome.tabs.query({});

    // 1. Explicit preferred tab ID if provided
    if (preferredTabId !== null && preferredTabId !== undefined && preferredTabId !== "") {
        const id = parseInt(preferredTabId, 10);
        if (!isNaN(id)) {
            const found = allTabs.find(t => t.id === id);
            if (found && !found.discarded) {
                activeAutomationTabId = found.id;
                return found;
            }
        }
    }

    // 2. Always check currently focused/active tab in user's window first
    const currentActiveTab = await getFocusedOrActiveTab();
    if (currentActiveTab && currentActiveTab.id && !currentActiveTab.discarded) {
        activeAutomationTabId = currentActiveTab.id;
        return currentActiveTab;
    }

    // 3. If activeAutomationTabId points to a live tab, use it
    if (activeAutomationTabId !== null) {
        const id = parseInt(activeAutomationTabId, 10);
        if (!isNaN(id)) {
            const tab = allTabs.find(t => t.id === id);
            if (tab && !tab.discarded) {
                return tab;
            } else {
                activeAutomationTabId = null;
            }
        }
    }

    // 4. Fallback to whatever active tab exists without force-activating tab index 0
    const fallbackTab = allTabs.length > 0 ? allTabs[0] : null;
    if (fallbackTab && fallbackTab.id) {
        activeAutomationTabId = fallbackTab.id;
    }
    return fallbackTab;
}
let lastRecordedTeachUrl = "";

/**
 * Dispatches teach_mode_stop to every tab except keepTabId so only
 * the currently active tab displays the live recording HUD pill.
 */
async function deactivateTeachHUDOnOtherTabs(keepTabId = null) {
    try {
        const allTabs = await chrome.tabs.query({});
        for (const t of allTabs) {
            if (t.id && t.id !== keepTabId) {
                chrome.tabs.sendMessage(t.id, { action: "teach_mode_stop" }).catch(() => {});
                // Forcibly purge HUD DOM element directly in tab context
                const tUrl = t.url || "";
                if (tUrl.startsWith("http://") || tUrl.startsWith("https://")) {
                    chrome.scripting.executeScript({
                        target: { tabId: t.id },
                        func: () => {
                            const el = document.getElementById("nexus-teach-hud-root");
                            if (el) el.remove();
                        }
                    }).catch(() => {});
                }
            }
        }
    } catch (_) {}
}

/**
 * Emits a navigation/site transition event to the backend so the exact
 * visited site/URL is persisted into the demonstrated skill sequence.
 */
function emitTeachNavigation(url, title = "", switchType = "tab_activated") {
    if (!isTeachModeRunning || !teachSessionId || !url || !url.startsWith("http")) return;

    // Avoid duplicate back-to-back navigation recordings of the exact same URL
    if (url === lastRecordedTeachUrl && switchType === "url_changed") return;
    lastRecordedTeachUrl = url;

    let hostname = "";
    let domain = "";
    try {
        const parsed = new URL(url);
        hostname = parsed.hostname;
        const parts = hostname.split(".");
        domain = parts.length > 2 ? parts.slice(-2).join(".") : hostname;
    } catch (_) {}

    const cleanTitle = (title || "").trim();
    const displaySub = cleanTitle ? `${cleanTitle.slice(0, 24)} (${hostname})` : hostname || url;
    const label = switchType === "tab_activated" ? "Switch Tab" : "Navigate";
    const tabAction = {
        type: "nav",
        label: label,
        sub: displaySub,
        desc: `${label === "Switch Tab" ? "Switched to" : "Visited"} ${hostname || cleanTitle || url}`,
        timestamp: Date.now()
    };
    recordedActionsHistory.push(tabAction);

    wsSend({
        type: "teach_event",
        session_id: teachSessionId,
        event: {
            environment: "browser",
            event_type: "navigate",
            url: url,
            value: url,
            metadata: {
                title: cleanTitle || url,
                hostname: hostname,
                domain: domain,
                action: switchType
            }
        }
    });
}

/**
 * Transfers and synchronizes the live teach recording HUD instantly
 * to the specified tab, carrying over timer, pause state, and recorded steps.
 */
async function syncTeachHUDToTab(tabId, isNewTabSwitch = false) {
    if (!isTeachModeRunning || !tabId) return;
    try {
        const tab = await chrome.tabs.get(tabId);
        const url = tab.url || tab.pendingUrl || "";

        // If active tab is an internal page (newtab, settings, etc.), hide HUD on all tabs & stay on user's tab
        if (!url || url.startsWith("chrome://") || url.startsWith("edge://") || url.startsWith("about:") || url.startsWith("chrome-extension://") || url.startsWith("chrome-search://")) {
            await deactivateTeachHUDOnOtherTabs(null);
            activeTeachModeTabId = tabId;
            return;
        }

        // Hide HUD on all other tabs so only the active tab shows it
        await deactivateTeachHUDOnOtherTabs(tabId);
        activeTeachModeTabId = tabId;

        if (isNewTabSwitch && (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("file://"))) {
            emitTeachNavigation(url, tab.title, "tab_activated");
        }

        const teachPayload = {
            session_id: teachSessionId,
            prompt: currentTeachPrompt,
            elapsed_seconds: Math.floor((Date.now() - teachStartedAt) / 1000),
            is_paused: isTeachPaused,
            actions: recordedActionsHistory,
            resume: true
        };

        // Try direct message first (fastest path if content script already loaded)
        try {
            await chrome.tabs.sendMessage(tabId, { action: "teach_mode_start", payload: teachPayload });
            return;
        } catch (_) {}

        // Content script not yet present on tab: inject defensively and start HUD
        try {
            await chrome.scripting.executeScript({
                target: { tabId: tabId },
                files: ["content.js"]
            });
            await chrome.tabs.sendMessage(tabId, { action: "teach_mode_start", payload: teachPayload });
        } catch (_) {
            // Short retry in case tab DOM was still initializing
            setTimeout(async () => {
                try {
                    await chrome.tabs.sendMessage(tabId, { action: "teach_mode_start", payload: teachPayload });
                } catch (_) {}
            }, 120);
        }
    } catch (_) {}
}

// Track user tab activations (instant switch when clicking another tab)
chrome.tabs.onActivated.addListener(async (activeInfo) => {
    try {
        const tab = await chrome.tabs.get(activeInfo.tabId);
        if (tab && tab.id && !tab.discarded) {
            const url = tab.url || tab.pendingUrl || "";
            if (isAutomationRunning && !url.startsWith("chrome://") && !url.startsWith("chrome-extension://") && !url.startsWith("edge://")) {
                activeAutomationTabId = tab.id;
                await syncOverlayToActiveTab(tab.id);
            }
            // Transfer teach recording HUD instantly to the activated tab
            if (isTeachModeRunning) {
                activeTeachModeTabId = activeInfo.tabId;
                await syncTeachHUDToTab(activeInfo.tabId, true);
            }
        }
    } catch (_) {}
});

// Track newly created tabs (e.g. target="_blank", window.open, Ctrl+T)
chrome.tabs.onCreated.addListener(async (tab) => {
    if (isAutomationRunning && tab && tab.id) {
        if (tab.active || tab.openerTabId === activeAutomationTabId) {
            activeAutomationTabId = tab.id;
        }
    }
    if (isTeachModeRunning && tab && tab.id) {
        if (tab.active) {
            activeTeachModeTabId = tab.id;
            await syncTeachHUDToTab(tab.id, true);
        }
    }
});

// When URL changes or tab finishes loading, ensure live HUD & navigation events are captured
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
    if (isAutomationRunning && tabId === activeAutomationTabId && changeInfo.status === "complete") {
        const url = tab?.url || "";
        if (url.startsWith("http://") || url.startsWith("https://") || url.startsWith("file://")) {
            await syncOverlayToActiveTab(tabId);
        }
    }
    if (isTeachModeRunning) {
        const activeUrl = changeInfo.url || tab?.url || "";
        // 1. Detect navigation immediately when URL changes on active tab or when user enters a new site
        if (activeUrl.startsWith("http://") || activeUrl.startsWith("https://") || activeUrl.startsWith("file://")) {
            if (changeInfo.url) {
                emitTeachNavigation(changeInfo.url, tab?.title, "url_changed");
                if (tab?.active) {
                    await syncTeachHUDToTab(tabId, false);
                }
            }
        }
        // 2. When page completes loading, re-verify HUD presence on active tab
        if (changeInfo.status === "complete" && tab?.active) {
            await syncTeachHUDToTab(tabId, false);
        }
    }
});

// When user switches Chrome windows, follow active tab in the newly focused window
if (chrome.windows && chrome.windows.onFocusChanged) {
    chrome.windows.onFocusChanged.addListener(async (windowId) => {
        if (!isTeachModeRunning || windowId === chrome.windows.WINDOW_ID_NONE) return;
        try {
            const tabs = await chrome.tabs.query({ active: true, windowId: windowId });
            if (tabs && tabs.length > 0 && tabs[0].id) {
                await syncTeachHUDToTab(tabs[0].id, true);
            }
        } catch (_) {}
    });
}

async function handleCommand(action, payload) {
    switch (action) {
        case "ping":
            return { pong: true, time: Date.now() };

        // ── Teach Mode Commands ─────────────────────────────────
        case "start_teach_mode": {
            let targetTab = await getTargetAutomationTab(payload?.tab_id);

            if (!isRecordableTeachTab(targetTab)) {
                const tabs = await chrome.tabs.query({});
                targetTab = tabs.find(isRecordableTeachTab) || null;
            }

            if (!targetTab || !targetTab.id || !isRecordableTeachTab(targetTab)) {
                throw new Error("Open a regular http or https page before starting browser teaching.");
            }
            if (targetTab.windowId) {
                await chrome.windows.update(targetTab.windowId, { focused: true }).catch(() => {});
            }

            isTeachModeRunning = true;
            activeTeachModeTabId = targetTab.id;
            teachSessionId = payload?.session_id || `teach-${Date.now()}`;
            currentTeachPrompt = payload?.prompt || "";
            teachStartedAt = Date.now();
            isTeachPaused = false;
            recordedActionsHistory = [];
            lastRecordedTeachUrl = "";

            const isWebPage = true;

            if (isWebPage) {
                emitTeachNavigation(targetTab.url, targetTab.title, "initial_page");
            }

            const initialPayload = {
                session_id: teachSessionId,
                prompt: currentTeachPrompt,
                elapsed_seconds: 0,
                is_paused: isTeachPaused,
                actions: recordedActionsHistory,
            };

            if (isWebPage) {
                // Mount and initialize HUD onto active tab asynchronously
                (async () => {
                    try {
                        await chrome.tabs.sendMessage(targetTab.id, {
                            action: "teach_mode_start",
                            payload: initialPayload
                        });
                    } catch (_) {
                        try {
                            await chrome.scripting.executeScript({
                                target: { tabId: targetTab.id },
                                files: ["content.js"]
                            });
                            await chrome.tabs.sendMessage(targetTab.id, {
                                action: "teach_mode_start",
                                payload: initialPayload
                            });
                        } catch (e) {
                            console.error("[NEXUS Extension] Could not inject content script for teach mode:", e);
                        }
                    }
                })();
            }

            return { success: true, tab_id: targetTab.id, session_id: teachSessionId };
        }

        case "pause_teach_mode": {
            isTeachPaused = true;
            if (activeTeachModeTabId) {
                await chrome.tabs.sendMessage(activeTeachModeTabId, { action: "teach_mode_pause" }).catch(() => {});
            }
            return { success: true };
        }

        case "resume_teach_mode": {
            isTeachPaused = false;
            if (activeTeachModeTabId) {
                await chrome.tabs.sendMessage(activeTeachModeTabId, { action: "teach_mode_resume" }).catch(() => {});
            }
            return { success: true };
        }

        case "stop_teach_mode": {
            if (activeTeachModeTabId) {
                await chrome.tabs.sendMessage(activeTeachModeTabId, { action: "teach_mode_stop" }).catch(() => {});
            }
            const oldSession = teachSessionId;
            isTeachModeRunning = false;
            activeTeachModeTabId = null;
            teachSessionId = null;
            currentTeachPrompt = "";
            recordedActionsHistory = [];
            isTeachPaused = false;
            return { success: true, session_id: oldSession };
        }

        case "get_tabs": {
            const tabs = await chrome.tabs.query({});
            return {
                count: tabs.length,
                active_tab_id: activeAutomationTabId,
                tabs: tabs.map(t => ({
                    id: t.id,
                    title: t.title,
                    url: t.url,
                    active: t.active,
                    is_automation_tab: t.id === activeAutomationTabId
                }))
            };
        }

        case "switch_tab": {
            const rawId = payload?.tab_id ?? payload?.target_id ?? payload?.id;
            const targetUrl = payload?.url || payload?.url_match || "";
            const targetTitle = payload?.title || payload?.title_match || "";

            const allTabs = await chrome.tabs.query({});
            let targetTab = null;

            // 1. By integer ID if provided
            if (rawId !== undefined && rawId !== null && rawId !== "") {
                const parsedId = parseInt(rawId, 10);
                if (!isNaN(parsedId)) {
                    targetTab = allTabs.find(t => t.id === parsedId);
                }
            }

            // 2. By URL match if not found yet
            if (!targetTab && (targetUrl || (typeof rawId === "string" && (rawId.includes("http") || rawId.includes(".") || rawId.includes("/"))))) {
                const queryUrl = String(targetUrl || rawId).toLowerCase().trim();
                targetTab = allTabs.find(t => t.url && t.url.toLowerCase().includes(queryUrl));
            }

            // 3. By Title match if not found yet
            if (!targetTab && (targetTitle || (typeof rawId === "string" && isNaN(parseInt(rawId, 10))))) {
                const queryTitle = String(targetTitle || rawId).toLowerCase().trim();
                targetTab = allTabs.find(t => t.title && t.title.toLowerCase().includes(queryTitle));
            }

            if (!targetTab) {
                const tabList = allTabs.map(t => `[ID: ${t.id}] ${t.title || 'Untitled'} (${t.url || 'No URL'})`).join("\n");
                throw new Error(`Tab not found matching '${rawId || targetUrl || targetTitle}'. Open tabs:\n${tabList}`);
            }

            const updatedTab = await chrome.tabs.update(targetTab.id, { active: true });
            if (updatedTab.windowId) {
                await chrome.windows.update(updatedTab.windowId, { focused: true }).catch(() => {});
            }
            activeAutomationTabId = updatedTab.id;
            isAutomationRunning = true;
            await deactivateOverlayOnOtherTabs(updatedTab.id);
            await syncOverlayToActiveTab(updatedTab.id);

            return {
                success: true,
                tab_id: updatedTab.id,
                title: updatedTab.title,
                url: updatedTab.url
            };
        }

        case "get_media_state": {
            const allTabs = await chrome.tabs.query({});
            const mediaCandidates = [];
            
            for (const t of allTabs) {
                if (!t.url || t.discarded) continue;
                const urlLower = t.url.toLowerCase();
                const isMediaDomain = urlLower.includes("youtube.com") || 
                    urlLower.includes("spotify.com") || 
                    urlLower.includes("soundcloud.com") || 
                    urlLower.includes("music.apple.com") ||
                    urlLower.includes("netflix.com") ||
                    urlLower.includes("twitch.tv");
                
                if (t.audible || isMediaDomain) {
                    let mediaInfo = { is_playing: Boolean(t.audible), title: t.title, service: isMediaDomain ? (urlLower.includes("spotify") ? "spotify" : urlLower.includes("youtube") ? "youtube" : "web") : "web" };
                    try {
                        const res = await sendWithTimeout(t.id, { action: "get_media_info" }, 1500);
                        if (res && res.success && res.data) {
                            mediaInfo = res.data;
                        }
                    } catch (_) {}
                    mediaCandidates.push({
                        tab_id: t.id,
                        title: t.title,
                        url: t.url,
                        audible: Boolean(t.audible),
                        active: Boolean(t.active),
                        media_info: mediaInfo
                    });
                }
            }
            return {
                count: mediaCandidates.length,
                has_active_media: mediaCandidates.some(m => m.audible || m.media_info?.is_playing),
                tabs: mediaCandidates
            };
        }

        case "media_control": {
            const act = (payload?.action || "toggle").toLowerCase().trim();
            const serviceTarget = (payload?.service || "").toLowerCase().trim();
            const tabIdTarget = payload?.tab_id;

            const allTabs = await chrome.tabs.query({});
            let targetTab = null;

            // 1. Explicit Tab ID
            if (tabIdTarget) {
                targetTab = allTabs.find(t => t.id === parseInt(tabIdTarget, 10));
            }

            // 2. Audible tab
            if (!targetTab) {
                if (serviceTarget) {
                    targetTab = allTabs.find(t => t.audible && t.url && t.url.toLowerCase().includes(serviceTarget));
                }
                if (!targetTab) {
                    targetTab = allTabs.find(t => t.audible);
                }
            }

            // 3. Domain match
            if (!targetTab && serviceTarget) {
                targetTab = allTabs.find(t => t.url && t.url.toLowerCase().includes(serviceTarget));
            }

            // 4. Any known media tab (YouTube, Spotify, SoundCloud, Apple Music)
            if (!targetTab) {
                targetTab = allTabs.find(t => {
                    const u = (t.url || "").toLowerCase();
                    return u.includes("open.spotify.com") || u.includes("youtube.com") || u.includes("music.youtube.com") || u.includes("soundcloud.com");
                });
            }

            // 5. Active tab fallback
            if (!targetTab) {
                targetTab = await getFocusedOrActiveTab();
            }

            if (!targetTab || !targetTab.id) {
                throw new Error("No media tab found in browser.");
            }

            // Handle tab-level mute/unmute if requested
            if (act === "mute" || act === "unmute") {
                try {
                    const shouldMute = act === "mute";
                    await chrome.tabs.update(targetTab.id, { muted: shouldMute });
                } catch (_) {}
            }

            // Dispatch to content script
            let resultData = null;
            try {
                const res = await sendWithTimeout(targetTab.id, { action: "control_media", payload: { action: act, volume_delta: payload?.volume_delta } }, 3000);
                if (res && res.success) {
                    resultData = res.data;
                }
            } catch (err) {
                // Injected & retry
                try {
                    await chrome.scripting.executeScript({ target: { tabId: targetTab.id }, files: ["content.js"] });
                    await new Promise(r => setTimeout(r, 200));
                    const retryRes = await sendWithTimeout(targetTab.id, { action: "control_media", payload: { action: act, volume_delta: payload?.volume_delta } }, 3000);
                    if (retryRes && retryRes.success) {
                        resultData = retryRes.data;
                    }
                } catch (_) {}
            }

            return {
                success: true,
                action: act,
                tab_id: targetTab.id,
                tab_title: targetTab.title,
                url: targetTab.url,
                result: resultData
            };
        }

        case "play_web_music": {
            const svc = (payload?.service || "spotify").toLowerCase().trim();
            const query = (payload?.query || "").trim();
            const autoPlay = payload?.auto_play !== false;

            let targetUrl = "";
            if (svc.includes("spotify")) {
                targetUrl = query ? `https://open.spotify.com/search/${encodeURIComponent(query)}` : "https://open.spotify.com";
            } else if (svc.includes("youtube_music") || svc === "ytm") {
                targetUrl = query ? `https://music.youtube.com/search?q=${encodeURIComponent(query)}` : "https://music.youtube.com";
            } else if (svc.includes("youtube") || svc === "yt") {
                targetUrl = query ? `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}` : "https://www.youtube.com";
            } else if (svc.includes("soundcloud")) {
                targetUrl = query ? `https://soundcloud.com/search?q=${encodeURIComponent(query)}` : "https://soundcloud.com";
            } else {
                targetUrl = query ? `https://open.spotify.com/search/${encodeURIComponent(query)}` : "https://open.spotify.com";
            }

            // Check if tab already exists for this service
            const allTabs = await chrome.tabs.query({});
            let existingTab = allTabs.find(t => {
                if (!t.url || t.discarded) return false;
                const u = t.url.toLowerCase();
                if (svc.includes("spotify") && u.includes("open.spotify.com")) return true;
                if (svc.includes("youtube_music") && u.includes("music.youtube.com")) return true;
                if (svc === "youtube" && u.includes("youtube.com") && !u.includes("music.youtube.com")) return true;
                return false;
            });

            let tabId = null;
            if (existingTab && existingTab.id) {
                tabId = existingTab.id;
                await chrome.tabs.update(tabId, { url: targetUrl, active: true });
                if (existingTab.windowId) {
                    await chrome.windows.update(existingTab.windowId, { focused: true }).catch(() => {});
                }
            } else {
                const newTab = await chrome.tabs.create({ url: targetUrl, active: true });
                tabId = newTab.id;
                if (newTab.windowId) {
                    await chrome.windows.update(newTab.windowId, { focused: true }).catch(() => {});
                }
            }

            // Wait for tab navigation to complete
            await new Promise((resolve) => {
                const timeout = setTimeout(resolve, 3500);
                const listener = (tid, info) => {
                    if (tid === tabId && info.status === "complete") {
                        chrome.tabs.onUpdated.removeListener(listener);
                        clearTimeout(timeout);
                        resolve();
                    }
                };
                chrome.tabs.onUpdated.addListener(listener);
            });

            // If auto_play is requested and a query was given, trigger top result click
            if (autoPlay && query) {
                try {
                    await chrome.scripting.executeScript({ target: { tabId }, files: ["content.js"] });
                    await new Promise(r => setTimeout(r, 400));
                    await sendWithTimeout(tabId, { action: "auto_play_top_result" }, 4000);
                } catch (_) {}
            }

            const updatedTab = await chrome.tabs.get(tabId).catch(() => null);
            return {
                success: true,
                tab_id: tabId,
                title: updatedTab?.title || "",
                url: targetUrl,
                service: svc,
                auto_play: autoPlay
            };
        }

        // ── Automation Overlay Forwarding ─────────────────────────────────────
        // These commands are forwarded to the active tab's content script AND
        // persisted into chrome.storage.local so the popup can react live.
        case "automation_start":
        case "automation_stop":
        case "automation_pause":
        case "automation_resume":
        case "automation_update_step":
        case "automation_request_input":
        case "automation_clear_input": {
            if (action === "automation_stop") {
                isAutomationRunning = false;
                activeAutomationTabId = null;
                automationSessionTabIds.clear();
                chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
                await deactivateOverlayOnOtherTabs(null);
                pushStepLog("ok", "Automation completed");
                return { success: true };
            }

            if (action !== "automation_start" && !isAutomationRunning) {
                return { success: true, skipped: true, reason: "No active browser automation session" };
            }

            if (action === "automation_start") {
                isAutomationRunning = true;
                automationSessionTabIds.clear();
                const initTab = await getActiveTab();
                activeAutomationTabId = initTab ? initTab.id : null;
                if (activeAutomationTabId) {
                    await deactivateOverlayOnOtherTabs(activeAutomationTabId);
                }
            }
            const activeTab = await getTargetAutomationTab();
            if (activeTab?.id) {
                activeAutomationTabId = activeTab.id;
                deactivateOverlayOnOtherTabs(activeTab.id);
            }

            // ── Persist state to storage for popup live-update ──
            try {
                if (action === "automation_start") {
                    const startedAt = Date.now();
                    chrome.storage.local.set({
                        nexusAutomationState: {
                            state: "running",
                            step: 0,
                            total: payload?.total_steps || 0,
                            action: payload?.task || "Starting…",
                            steps_done: 0,
                            retries: 0,
                            validations: { passed: 0, total: 0 },
                            started_at: startedAt
                        }
                    });
                    pushStepLog("info", `Started: ${payload?.task || "automation"}`);
                } else if (action === "automation_stop") {
                    chrome.storage.local.set({ nexusAutomationState: { state: "stopped" } });
                    pushStepLog("ok", "Automation completed");
                } else if (action === "automation_pause") {
                    chrome.storage.local.get(["nexusAutomationState"], (d) => {
                        const cur = d.nexusAutomationState || {};
                        chrome.storage.local.set({ nexusAutomationState: { ...cur, state: "paused" } });
                    });
                    pushStepLog("warn", "Automation paused");
                } else if (action === "automation_resume") {
                    chrome.storage.local.get(["nexusAutomationState"], (d) => {
                        const cur = d.nexusAutomationState || {};
                        chrome.storage.local.set({ nexusAutomationState: { ...cur, state: "running" } });
                    });
                    pushStepLog("info", "Automation resumed");
                } else if (action === "automation_update_step") {
                    const stepText = payload?.step || payload?.action || "";
                    const stepIdx = payload?.step_index ?? payload?.step ?? 0;
                    const totalSteps = payload?.total_steps ?? payload?.total ?? 0;
                    chrome.storage.local.get(["nexusAutomationState"], (d) => {
                        const cur = d.nexusAutomationState || {};
                        const update = {
                            ...cur,
                            state: "running",
                            step: stepIdx,
                            total: totalSteps,
                            action: stepText,
                            steps_done: payload?.steps_done ?? cur.steps_done ?? 0,
                            retries: payload?.retries ?? cur.retries ?? 0,
                            validations: payload?.validations ?? cur.validations ?? { passed: 0, total: 0 },
                            started_at: cur.started_at || Date.now()
                        };
                        chrome.storage.local.set({ nexusAutomationState: update });
                    });
                    if (stepText) {
                        const isVal = Boolean(payload?.is_validation);
                        const logType = payload?.validation_failed ? "err" : isVal ? "info" : "ok";
                        pushStepLog(logType, isVal ? `[VLM] ${stepText}` : `Step ${typeof stepIdx === 'number' ? stepIdx + 1 : stepIdx}: ${stepText}`);
                    }
                }
            } catch (_) {}

            // ── Forward to content script ──
            if (!activeTab?.id) return { success: true };
            const tabUrl = activeTab.url || activeTab.pendingUrl || "";
            if (tabUrl.startsWith("chrome://") || tabUrl.startsWith("chrome-extension://") || tabUrl.startsWith("about:") || tabUrl === "") {
                return { success: true, skipped: true };
            }
            try {
                await chrome.tabs.sendMessage(activeTab.id, { action, payload });
            } catch (_) {
                try {
                    await chrome.scripting.executeScript({
                        target: { tabId: activeTab.id },
                        files: ["content.js"]
                    });
                    await new Promise(r => setTimeout(r, 150));
                    await chrome.tabs.sendMessage(activeTab.id, { action, payload });
                } catch (_) {}
            }
            return { success: true };
        }

        case "navigate": {
            let { url, new_tab = false } = payload;
            if (!url.startsWith("http://") && !url.startsWith("https://") && !url.startsWith("chrome://") && !url.startsWith("file://") && !url.startsWith("about:")) {
                url = "https://" + url;
            }

            if (new_tab) {
                const tab = await chrome.tabs.create({ url: url, active: true });
                if (tab.windowId) {
                    await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
                }
                automationSessionTabIds.add(tab.id);
                activeAutomationTabId = tab.id;
                isAutomationRunning = true;
                await deactivateOverlayOnOtherTabs(tab.id);
                await syncOverlayToActiveTab(tab.id);
                return { success: true, action: "opened_tab", tab_id: tab.id, url: url };
            }

            const allTabs = await chrome.tabs.query({});

            // Helper to clean URL for comparing
            const cleanUrlForCompare = (u) => {
                if (!u) return "";
                try {
                    const parsed = new URL(u);
                    return (parsed.origin + parsed.pathname).toLowerCase().replace(/\/$/, "");
                } catch (_) {
                    return u.toLowerCase().replace(/#.*$/, "").replace(/\/$/, "");
                }
            };

            const targetClean = cleanUrlForCompare(url);

            // 1. Check if ANY open tab already matches the target URL or web service
            let matchingTab = allTabs.find(t => {
                if (!t.url || t.discarded) return false;
                return cleanUrlForCompare(t.url) === targetClean;
            });

            // If not found by exact clean URL, check if target is a root domain/app and an open tab is on that same domain
            if (!matchingTab) {
                try {
                    const targetParsed = new URL(url);
                    const isRootOrSearch = targetParsed.pathname === "/" || targetParsed.pathname === "" || targetParsed.pathname === "/search";
                    if (isRootOrSearch) {
                        const targetHost = targetParsed.hostname.replace(/^www\./, "");
                        matchingTab = allTabs.find(t => {
                            if (!t.url || t.discarded) return false;
                            try {
                                const tabParsed = new URL(t.url);
                                return tabParsed.hostname.replace(/^www\./, "") === targetHost;
                            } catch (_) {
                                return false;
                            }
                        });
                    }
                } catch (_) {}
            }

            if (matchingTab && matchingTab.id) {
                // Gracefully switch to the already-open tab without altering its URL or closing any tab!
                await chrome.tabs.update(matchingTab.id, { active: true });
                if (matchingTab.windowId) {
                    await chrome.windows.update(matchingTab.windowId, { focused: true }).catch(() => {});
                }
                automationSessionTabIds.add(matchingTab.id);
                activeAutomationTabId = matchingTab.id;
                isAutomationRunning = true;
                await deactivateOverlayOnOtherTabs(matchingTab.id);
                await syncOverlayToActiveTab(matchingTab.id);
                return {
                    success: true,
                    action: "switched_to_tab",
                    tab_id: matchingTab.id,
                    url: matchingTab.url,
                    title: matchingTab.title
                };
            }

            // 2. No matching tab found. Inspect current active tab.
            const activeTab = await getTargetAutomationTab();
            const activeUrl = activeTab?.url || activeTab?.pendingUrl || "";
            const isBlankTab = !activeTab || !activeUrl ||
                activeUrl === "about:blank" ||
                activeUrl.startsWith("about:") ||
                activeUrl.startsWith("chrome://newtab") ||
                activeUrl.startsWith("chrome://welcome") ||
                activeUrl.startsWith("edge://newtab");

            // If current tab is genuinely blank/new tab, navigate it directly (no user content to overwrite)
            if (activeTab && activeTab.id && isBlankTab && !activeUrl.startsWith("chrome://extensions")) {
                const updated = await chrome.tabs.update(activeTab.id, { url: url, active: true });
                if (updated.windowId) {
                    await chrome.windows.update(updated.windowId, { focused: true }).catch(() => {});
                }
                automationSessionTabIds.add(updated.id);
                activeAutomationTabId = updated.id;
                isAutomationRunning = true;
                await syncOverlayToActiveTab(updated.id);
                return { success: true, action: "navigated_blank_tab", tab_id: updated.id, url: url };
            }

            // If current active tab was created by NEXUS during this automation session, reuse it
            if (activeTab && activeTab.id && automationSessionTabIds.has(activeTab.id)) {
                const updated = await chrome.tabs.update(activeTab.id, { url: url, active: true });
                if (updated.windowId) {
                    await chrome.windows.update(updated.windowId, { focused: true }).catch(() => {});
                }
                activeAutomationTabId = updated.id;
                isAutomationRunning = true;
                await syncOverlayToActiveTab(updated.id);
                return { success: true, action: "navigated_session_tab", tab_id: updated.id, url: url };
            }

            // 3. Current active tab has live user content (YouTube, Gmail, personal tabs, etc.):
            // NEVER overwrite or replace the URL of the user's tab! Open a new tab for this automation.
            const tab = await chrome.tabs.create({ url: url, active: true });
            if (tab.windowId) {
                await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
            }
            automationSessionTabIds.add(tab.id);
            activeAutomationTabId = tab.id;
            isAutomationRunning = true;
            await deactivateOverlayOnOtherTabs(tab.id);
            await syncOverlayToActiveTab(tab.id);
            return {
                success: true,
                action: "opened_tab",
                tab_id: tab.id,
                url: url,
                reason: "preserved_existing_tab"
            };
        }

        default: {
            // Forward in-page actions to content script in the target automation tab
            let activeTab = await getTargetAutomationTab(payload?.tab_id);
            if (!activeTab || !activeTab.id) {
                throw new Error("No active Chrome tab found to execute command.");
            }

            let tabUrl = activeTab.url || activeTab.pendingUrl || "";
            // Can't inject into chrome://, edge://, about:, or extension pages
            if (
                tabUrl.startsWith("chrome://") ||
                tabUrl.startsWith("chrome-extension://") ||
                tabUrl.startsWith("edge://") ||
                tabUrl.startsWith("about:") ||
                tabUrl === ""
            ) {
                if (action === "inspect_dom") {
                    return {
                        url: tabUrl || "about:blank",
                        title: activeTab.title || "New Tab",
                        tab_id: activeTab.id,
                        interactive_elements: [],
                        forms: [],
                        is_restricted_tab: true,
                        note: `The active tab is '${tabUrl || "New Tab"}'. Please navigate to a website first using browser_navigate or switch tabs using browser_switch_tab.`
                    };
                }
                if (action === "get_page_source") {
                    return {
                        url: tabUrl || "about:blank",
                        title: activeTab.title || "New Tab",
                        tab_id: activeTab.id,
                        html: `<html><body><p>Active tab is ${tabUrl || "New Tab"}.</p></body></html>`
                    };
                }

                const allTabs = await chrome.tabs.query({});
                const realTab = allTabs.find(t => t.url && (t.url.startsWith("http://") || t.url.startsWith("https://")));
                if (realTab && realTab.id) {
                    activeAutomationTabId = realTab.id;
                    activeTab = realTab;
                    tabUrl = realTab.url || "";
                } else {
                    throw new Error(
                        `Cannot execute '${action}' on restricted page: ${tabUrl || "new/blank tab"}. Navigate to a real web page first.`
                    );
                }
            }

            // Settle check: If tab is currently loading, wait up to 1500ms for it to finish or commit
            if (activeTab.status === "loading") {
                await new Promise((resolve) => {
                    const timer = setTimeout(resolve, 1500);
                    const onUpdatedListener = (tabId, info) => {
                        if (tabId === activeTab.id && (info.status === "complete" || info.url)) {
                            chrome.tabs.onUpdated.removeListener(onUpdatedListener);
                            clearTimeout(timer);
                            resolve();
                        }
                    };
                    chrome.tabs.onUpdated.addListener(onUpdatedListener);
                });
                try {
                    activeTab = await chrome.tabs.get(activeTab.id);
                    tabUrl = activeTab.url || tabUrl;
                } catch (_) {}
            }

            // Helper: sendMessage with explicit timeout so it never hangs
            function sendWithTimeout(tabId, msg, timeoutMs = 5000) {
                return Promise.race([
                    chrome.tabs.sendMessage(tabId, msg),
                    new Promise((_, reject) =>
                        setTimeout(() => reject(new Error(`Content script did not respond within ${timeoutMs}ms`)), timeoutMs)
                    )
                ]);
            }

            let resultData = null;
            // Attempt 1: Try sending to existing content script
            try {
                const response = await sendWithTimeout(activeTab.id, { action, payload });
                if (response && response.success) {
                    resultData = response.data;
                } else {
                    throw new Error(response?.error || `Content script returned failure for '${action}'.`);
                }
            } catch (firstErr) {
                // Attempt 2: Inject content script and retry
                try {
                    await chrome.scripting.executeScript({
                        target: { tabId: activeTab.id },
                        files: ["content.js"]
                    });
                    // Wait for script to initialise and register its listener
                    await new Promise(r => setTimeout(r, 400));

                    // Ping to verify the content script is actually alive
                    let pingOk = false;
                    try {
                        const ping = await sendWithTimeout(activeTab.id, { action: "ping", payload: {} }, 2000);
                        pingOk = ping && ping.success;
                    } catch (_) {}

                    if (!pingOk) {
                        throw new Error(`Content script injected but not responding on '${tabUrl}'. The page may block extension scripts.`);
                    }

                    const retryResponse = await sendWithTimeout(activeTab.id, { action, payload });
                    if (retryResponse && retryResponse.success) {
                        resultData = retryResponse.data;
                    } else {
                        throw new Error(retryResponse?.error || `'${action}' failed after content script injection.`);
                    }
                } catch (retryErr) {
                    const isTimeout = retryErr.message.includes("did not respond") || retryErr.message.includes("not responding");
                    throw new Error(
                        isTimeout
                            ? `Content script not available on '${tabUrl}'. Refresh the tab and try again.`
                            : retryErr.message
                    );
                }
            }

            // Post-action: If this was a click action and coordinates were returned,
            // dispatch native CDP mouse click for real browser isTrusted event!
            if (action === "click_element" || action === "secondary_cursor_click") {
                const coords = resultData?.coords;
                if (coords && typeof coords.x === "number" && typeof coords.y === "number") {
                    await dispatchNativeMouseClick(activeTab.id, coords.x, coords.y).catch(() => {});
                }
            } else if (action === "hover_element") {
                const coords = resultData?.coords;
                if (coords && typeof coords.x === "number" && typeof coords.y === "number") {
                    await dispatchNativeMouseMove(activeTab.id, coords.x, coords.y).catch(() => {});
                }
            }

            return resultData;
        }
    }
}

// Start connection on service worker launch
connectToNexus();

// Keep service worker alive with defensive alarm & interval
try {
    if (typeof chrome !== "undefined" && chrome.alarms && typeof chrome.alarms.create === "function") {
        chrome.alarms.create("nexus_heartbeat", { periodInMinutes: 0.5 });
        chrome.alarms.onAlarm.addListener((alarm) => {
            if (alarm.name === "nexus_heartbeat") {
                connectToNexus();
            }
        });
    }
} catch (e) {}

setInterval(() => {
    connectToNexus();
}, 3000);

// Active WebSocket ping heartbeat every 12 seconds keeps TCP connection alive
setInterval(() => {
    if (socket && socket.readyState === WebSocket.OPEN) {
        wsSend({ type: "ping" });
    } else {
        connectToNexus();
    }
}, 12000);
