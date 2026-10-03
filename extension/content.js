/**
 * NEXUS In-Page Content Script
 * Executes DOM queries, typing, clicks, and framework-level event dispatches.
 *
 * Wrapped in an IIFE with double-injection guard to prevent SyntaxErrors and re-declaration collisions.
 */
(() => {
    // Purge any orphan overlays left in the document from previous loads or reloads
    try {
        const orphans = document.querySelectorAll("#__nexus-overlay-root__, #nexus-widget");
        orphans.forEach(el => { try { el.remove(); } catch (_) {} });
    } catch (_) {}

    if (window.__NEXUS_CONTENT_LOADED__) {
        return;
    }
    window.__NEXUS_CONTENT_LOADED__ = true;

    // Maintain persistent Port keepalive to keep Chrome MV3 background service worker continuously awake
    let keepalivePort = null;
    function connectKeepalive() {
        try {
            if (!chrome?.runtime?.connect) return;
            keepalivePort = chrome.runtime.connect({ name: "nexus-keepalive" });
            keepalivePort.onDisconnect.addListener(() => {
                keepalivePort = null;
                setTimeout(connectKeepalive, 1500);
            });
        } catch (_) {}
    }
    connectKeepalive();
    setInterval(() => {
        try {
            chrome.runtime?.sendMessage?.({ action: "ping" }).catch?.(() => {});
        } catch (_) {}
    }, 8000);

    chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
        // Health-check from background
        if (request.action === "ping") {
            sendResponse({ success: true, data: { pong: true, url: window.location.href } });
            return true;
        }
        handleAction(request)
            .then(res => sendResponse({ success: true, data: res }))
            .catch(err => sendResponse({ success: false, error: err.message || String(err) }));
        return true; // Keep channel open for async response
    });

async function handleAction(req) {
    const { action, payload } = req;
    switch (action) {
        case "inspect_dom":
            return inspectDOM(payload);
        case "click_element":
            return clickElement(payload);
        case "hover_element":
            return hoverElement(payload);
        case "secondary_cursor_click":
            return secondaryCursorClick(payload);
        case "type_text":
            return typeText(payload);
        case "dismiss_popups":
            return dismissPopups();
        case "press_key":
            return pressKey(payload);
        case "select_option":
            return selectOption(payload);
        case "get_html":
            // Legacy: return text content. Use get_page_source for full HTML.
            return { html: document.body ? document.body.innerText.substring(0, 10000) : "" };
        case "get_page_source":
            return getPageSource(payload);
        case "execute_script":
            return executeScript(payload);
        case "scroll_to":
            return scrollToElement(payload);
        case "control_media":
            return controlMedia(payload);
        case "get_media_info":
            return getMediaInfo();
        case "auto_play_top_result":
            return autoPlayTopResult(payload);

        // ── Automation Overlay Controls ─────────────────────────────────
        case "automation_start":
            return nexusOverlay.show(payload || {});
        case "automation_stop":
            return nexusOverlay.hide();
        case "automation_pause":
            return nexusOverlay.setPaused(true);
        case "automation_resume":
            return nexusOverlay.setPaused(false);
        case "automation_disable_shield":
            return nexusOverlay.disableShield();
        case "automation_enable_shield":
            return nexusOverlay.enableShield();
        case "automation_update_step":
            return nexusOverlay.updateStep(payload || {});
        case "automation_request_input":
            return nexusOverlay.requestInput(payload || {});
        case "automation_clear_input":
            return nexusOverlay.clearInput();

        // ── Teach Mode Demonstration Controls ─────────────────────────
        case "teach_mode_start":
            return nexusTeachHUD.start(payload || {});
        case "teach_mode_pause":
            return nexusTeachHUD.setPaused(true);
        case "teach_mode_resume":
            return nexusTeachHUD.setPaused(false);
        case "teach_mode_stop":
            return nexusTeachHUD.stop();

        default:
            throw new Error(`Unknown content action: ${action}`);
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// NEXUS Demonstration Teach Mode HUD & Telemetry Observer
// Injected into an isolated Shadow DOM root. Captures resilient multi-attribute
// selectors, redacts sensitive inputs, and streams events to background worker.
// ─────────────────────────────────────────────────────────────────────────────
const nexusTeachHUD = (() => {
    let hostEl = null;
    let shadow = null;
    let isRecording = false;
    let isPaused = false;
    let currentSessionId = null;
    let timerInterval = null;
    let elapsedSeconds = 0;
    let recordedActions = [];
    let isDrawerOpen = false;
    let currentPrompt = "";

    function isSensitiveElement(el) {
        if (!el) return false;
        const type = (el.type || "").toLowerCase();
        if (type === "password" || type === "hidden") return true;

        const attrs = [
            el.getAttribute("autocomplete"),
            el.getAttribute("name"),
            el.getAttribute("id"),
            el.getAttribute("aria-label"),
            el.getAttribute("placeholder"),
            typeof el.className === "string" ? el.className : ""
        ].map(a => (typeof a === "string" ? a.toLowerCase() : ""));

        const sensitiveWords = ["password", "passcode", "creditcard", "cc-number", "cvv", "cvc", "ssn", "pin", "secret", "token", "otp", "auth"];
        return attrs.some(a => sensitiveWords.some(sw => a.includes(sw)));
    }

    function getElementXPath(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return "";
        if (element.id && !element.id.match(/\d{4,}/)) return `//*[@id="${element.id}"]`;
        const sameTagSiblings = Array.from(element.parentNode ? element.parentNode.children : []).filter(
            sib => sib.tagName === element.tagName
        );
        const idx = sameTagSiblings.indexOf(element) + 1;
        const tag = element.tagName.toLowerCase();
        const path = sameTagSiblings.length > 1 ? `${tag}[${idx}]` : tag;
        return element.parentNode && element.parentNode.nodeType === Node.ELEMENT_NODE && element.parentNode !== document.body
            ? `${getElementXPath(element.parentNode)}/${path}`
            : `//${path}`;
    }

    function generateSelectorBundle(element) {
        if (!element || element.nodeType !== Node.ELEMENT_NODE) return null;
        let rect = null;
        try {
            const r = element.getBoundingClientRect();
            rect = {
                x: Math.round(r.x),
                y: Math.round(r.y),
                width: Math.round(r.width),
                height: Math.round(r.height),
                top: Math.round(r.top),
                left: Math.round(r.left)
            };
        } catch (_) {}
        return {
            testId: element.getAttribute("data-testid") || element.getAttribute("data-cy") || element.getAttribute("data-test") || null,
            ariaLabel: element.getAttribute("aria-label") ? `[aria-label="${element.getAttribute("aria-label").replace(/"/g, '\\"')}"]` : null,
            role: element.getAttribute("role") || element.tagName.toLowerCase(),
            name: element.name ? `[name="${element.name.replace(/"/g, '\\"')}"]` : null,
            id: element.id && !element.id.match(/\d{4,}/) ? `#${element.id}` : null,
            cssPath: getCssSelector(element),
            xpath: getElementXPath(element),
            textAnchor: (element.innerText || element.textContent || "").trim().slice(0, 40) || null,
            placeholder: element.placeholder || element.getAttribute("placeholder") || null,
            title: element.title || element.getAttribute("title") || null,
            boundingRect: rect
        };
    }

    function getActionIconSVG(type) {
        if (type === "click") {
            return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="3"/><path d="m19 19-3.5-3.5"/><path d="M5 5l3.5 3.5"/></svg>`;
        }
        if (type === "type") {
            return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect width="20" height="16" x="2" y="4" rx="2"/><path d="M6 8h.01"/><path d="M10 8h.01"/><path d="M14 8h.01"/><path d="M18 8h.01"/><path d="M8 12h.01"/><path d="M12 12h.01"/><path d="M16 12h.01"/><path d="M7 16h10"/></svg>`;
        }
        if (type === "nav") {
            return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="3 11 22 2 13 21 11 13 3 11"/></svg>`;
        }
        return `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 14 14"/></svg>`;
    }

    function addActionToUI(actionObj) {
        if (!shadow) return;
        recordedActions.push(actionObj);

        requestAnimationFrame(() => {
            const pillCount = shadow.getElementById("teach-steps-pill");
            if (pillCount) {
                pillCount.textContent = `${recordedActions.length} step${recordedActions.length !== 1 ? "s" : ""}`;
                pillCount.style.display = "inline-flex";
            }

            const subAction = shadow.getElementById("teach-sub-action");
            if (subAction) {
                subAction.textContent = actionObj.desc;
            }

            const drawerCount = shadow.getElementById("drawer-counter");
            if (drawerCount) {
                drawerCount.textContent = `${recordedActions.length} action${recordedActions.length !== 1 ? "s" : ""}`;
            }

            const stepsList = shadow.getElementById("nexus-teach-steps-list");
            if (stepsList) {
                const emptyHint = stepsList.querySelector(".empty-steps-hint");
                if (emptyHint) emptyHint.remove();

                const idx = recordedActions.length;
                const item = document.createElement("div");
                item.className = "step-item";
                item.innerHTML = `
                    <span class="step-num">${idx}</span>
                    <span class="step-icon">${getActionIconSVG(actionObj.type)}</span>
                    <div class="step-text">
                        <span class="step-label">${actionObj.label}</span>
                        <span class="step-desc">${actionObj.sub || actionObj.desc}</span>
                    </div>
                    <span class="step-badge">latest</span>
                `;

                const oldBadges = stepsList.querySelectorAll(".step-badge");
                oldBadges.forEach(b => b.remove());

                stepsList.appendChild(item);
                stepsList.scrollTop = stepsList.scrollHeight;
            }
        });
    }

    function sendTeachEvent(eventType, target, extra = {}) {
        if (!isRecording || isPaused) return;
        if (hostEl && (hostEl.contains(target) || (target && target.shadowRoot && target.shadowRoot.contains(target)))) return;

        const isSensitive = isSensitiveElement(target);
        let val = extra.value !== undefined ? extra.value : (target ? target.value : null);
        if (isSensitive && val) {
            val = "[REDACTED_SECRET]";
        }

        let actionDesc = "";
        let actionLabel = "";
        let actionSub = "";
        let actionType = "other";

        if (eventType === "click") {
            const rawText = target ? (target.innerText || target.textContent || target.getAttribute("aria-label") || target.getAttribute("title") || target.tagName.toLowerCase()) : "";
            const text = (rawText || "").trim().slice(0, 32);
            actionLabel = "Click";
            actionSub = text ? `"${text}"` : (target ? `<${target.tagName.toLowerCase()}>` : "element");
            actionDesc = `Clicked ${actionSub}`;
            actionType = "click";
        } else if (eventType === "input" || eventType === "change") {
            const typedVal = isSensitive ? "••••••" : (val || "");
            const name = target?.getAttribute("placeholder") || target?.getAttribute("name") || target?.getAttribute("aria-label") || (target ? target.tagName.toLowerCase() : "input");
            actionLabel = "Type";
            actionSub = `"${typedVal.slice(0, 25)}" in ${name}`;
            actionDesc = `Entered ${actionSub}`;
            actionType = "type";
        } else if (eventType === "navigate") {
            const rawUrl = extra.value || window.location.href;
            let displayUrl = rawUrl;
            try {
                const u = new URL(rawUrl);
                displayUrl = `${u.hostname}${u.pathname.length > 1 ? u.pathname.slice(0, 25) : ''}`;
            } catch (_) {
                displayUrl = rawUrl.slice(0, 35);
            }
            actionLabel = "Navigate";
            actionSub = displayUrl;
            actionDesc = `Navigated to ${displayUrl}`;
            actionType = "nav";
        } else if (eventType === "keydown") {
            actionLabel = "Key";
            actionSub = extra.key || "press";
            actionDesc = `Pressed ${extra.key}`;
            actionType = "key";
        } else {
            actionLabel = eventType;
            actionSub = "";
            actionDesc = `${eventType} event`;
            actionType = "other";
        }

        addActionToUI({
            type: actionType,
            label: actionLabel,
            sub: actionSub,
            desc: actionDesc,
            timestamp: Date.now()
        });

        const eventData = {
            environment: "browser",
            event_type: eventType,
            url: window.location.href,
            selector_bundle: target ? generateSelectorBundle(target) : null,
            value: val,
            key: extra.key || null,
            is_sensitive: isSensitive,
            metadata: {
                tagName: target?.tagName?.toLowerCase() || null,
                targetText: isSensitive ? "[REDACTED]" : (target?.innerText || "").trim().slice(0, 30),
                ...extra.metadata
            }
        };

        try {
            chrome.runtime.sendMessage({
                type: "teach_event",
                payload: eventData,
                action_summary: {
                    type: actionType,
                    label: actionLabel,
                    sub: actionSub,
                    desc: actionDesc,
                    timestamp: Date.now()
                }
            });
        } catch (_) {}
    }

    let lastRecordedNavUrl = window.location.href;

    function checkClientSideUrlChange() {
        if (!isRecording || isPaused) return;
        const cur = window.location.href;
        if (cur !== lastRecordedNavUrl && cur.startsWith("http")) {
            lastRecordedNavUrl = cur;
            sendTeachEvent("navigate", null, {
                value: cur,
                metadata: {
                    title: document.title,
                    hostname: window.location.hostname,
                    action: "spa_navigation"
                }
            });
        }
    }

    let lastClickTime = 0;
    const EVENT_DEBOUNCE_MS = 80;

    function onDocClick(e) {
        if (!isRecording || isPaused) return;
        const now = Date.now();
        if (now - lastClickTime < EVENT_DEBOUNCE_MS) return;
        lastClickTime = now;
        const target = e.target;
        if (!target || (hostEl && hostEl.contains(target))) return;
        sendTeachEvent("click", target, { coords: { x: Math.round(e.clientX), y: Math.round(e.clientY) } });
        requestAnimationFrame(() => checkClientSideUrlChange());
    }

    function onDocInput(e) {
        if (!isRecording || isPaused) return;
        const target = e.target;
        if (!target || (hostEl && hostEl.contains(target))) return;
        sendTeachEvent("input", target, { value: target.value });
    }

    function onDocChange(e) {
        if (!isRecording || isPaused) return;
        const target = e.target;
        if (!target || (hostEl && hostEl.contains(target))) return;
        sendTeachEvent("change", target, { value: target.value });
    }

    function onDocKeyDown(e) {
        if (!isRecording || isPaused) return;
        const target = e.target;
        if (hostEl && hostEl.contains(target)) return;
        if (e.key === "Enter" || e.key === "Tab" || e.key === "Escape" || ((e.ctrlKey || e.metaKey) && e.key.length === 1)) {
            sendTeachEvent("keydown", target, { key: e.key, value: target?.value });
        }
    }

    function attachListeners() {
        detachListeners();
        document.addEventListener("click", onDocClick, true);
        document.addEventListener("input", onDocInput, true);
        document.addEventListener("change", onDocChange, true);
        document.addEventListener("keydown", onDocKeyDown, true);
        window.addEventListener("popstate", checkClientSideUrlChange);
        window.addEventListener("hashchange", checkClientSideUrlChange);
    }

    function detachListeners() {
        document.removeEventListener("click", onDocClick, true);
        document.removeEventListener("input", onDocInput, true);
        document.removeEventListener("change", onDocChange, true);
        document.removeEventListener("keydown", onDocKeyDown, true);
        window.removeEventListener("popstate", checkClientSideUrlChange);
        window.removeEventListener("hashchange", checkClientSideUrlChange);
    }

    function renderHUD(promptText = "") {
        if (hostEl) {
            if (!document.contains(hostEl) && document.documentElement) {
                document.documentElement.appendChild(hostEl);
            }
            if (shadow) {
                const titleEl = shadow.getElementById("teach-prompt-title");
                if (titleEl && promptText) titleEl.textContent = promptText;
            }
            return;
        }
        hostEl = document.createElement("div");
        hostEl.id = "nexus-teach-hud-root";
        hostEl.style.cssText = "all: initial; position: fixed; top: 16px; left: 50%; transform: translateX(-50%); z-index: 2147483647; font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif; pointer-events: none !important;";
        shadow = hostEl.attachShadow({ mode: "open" });

        shadow.innerHTML = `
            <style>
                * { box-sizing: border-box; margin: 0; padding: 0; }

                #teach-container {
                    display: flex;
                    flex-direction: column;
                    align-items: center;
                    width: 560px;
                    max-width: 95vw;
                    pointer-events: all !important;
                    user-select: none;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
                }

                #teach-banner {
                    position: relative;
                    width: 100%;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                    background: rgba(10, 11, 15, 0.94);
                    backdrop-filter: blur(24px) saturate(180%);
                    -webkit-backdrop-filter: blur(24px) saturate(180%);
                    border: 1px solid rgba(255, 255, 255, 0.09);
                    border-radius: 12px;
                    padding: 6px 10px 6px 12px;
                    box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 16px 36px -4px rgba(0, 0, 0, 0.75);
                    color: #f8fafc;
                    transition: border-color 0.2s, box-shadow 0.2s;
                }
                #teach-banner.paused {
                    border-color: rgba(245, 158, 11, 0.35);
                }

                /* REC badge */
                .rec-badge {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                    padding: 3px 8px;
                    background: rgba(239, 68, 68, 0.08);
                    border: 1px solid rgba(239, 68, 68, 0.22);
                    border-radius: 6px;
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                    font-size: 10.5px;
                    font-weight: 600;
                    color: #fca5a5;
                    letter-spacing: 0.03em;
                    flex-shrink: 0;
                }
                .rec-badge.paused {
                    background: rgba(245, 158, 11, 0.08);
                    border-color: rgba(245, 158, 11, 0.25);
                    color: #fde68a;
                }
                .rec-dot {
                    width: 5px;
                    height: 5px;
                    border-radius: 50%;
                    background: #ef4444;
                    box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
                    animation: recPulse 1.8s ease-in-out infinite;
                }
                .rec-dot.paused {
                    background: #f59e0b;
                    box-shadow: none;
                    animation: none;
                }
                @keyframes recPulse {
                    0%, 100% { opacity: 1; transform: scale(1); }
                    50% { opacity: 0.35; transform: scale(0.85); }
                }

                /* Environment badge */
                .env-badge {
                    display: flex;
                    align-items: center;
                    gap: 4.5px;
                    padding: 3px 7px;
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.07);
                    border-radius: 6px;
                    font-size: 10px;
                    font-weight: 500;
                    color: rgba(255, 255, 255, 0.55);
                    flex-shrink: 0;
                }
                .env-badge svg {
                    color: rgba(255, 255, 255, 0.55);
                }

                /* Content middle */
                .teach-content {
                    flex: 1 1 0%;
                    min-width: 0;
                    overflow: hidden;
                    display: flex;
                    flex-direction: column;
                    justify-content: center;
                    gap: 2px;
                    padding: 0 4px;
                }
                .teach-title-row {
                    display: flex;
                    align-items: center;
                    gap: 6px;
                }
                .teach-prompt-title {
                    font-size: 12px;
                    font-weight: 600;
                    color: #ffffff;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    letter-spacing: -0.01em;
                }
                .teach-steps-pill {
                    font-size: 9.5px;
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                    padding: 1px 6px;
                    background: rgba(255, 255, 255, 0.04);
                    border: 1px solid rgba(255, 255, 255, 0.07);
                    border-radius: 4px;
                    color: rgba(255, 255, 255, 0.5);
                    flex-shrink: 0;
                    font-weight: 500;
                }
                .teach-sub-action {
                    font-size: 10.5px;
                    color: rgba(255, 255, 255, 0.45);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    font-weight: 400;
                    letter-spacing: -0.005em;
                }

                /* Actions group */
                .teach-actions {
                    display: flex;
                    align-items: center;
                    gap: 4px;
                    flex-shrink: 0;
                }
                .teach-btn {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 4px;
                    height: 26px;
                    min-width: 26px;
                    padding: 0 7px;
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    background: rgba(255, 255, 255, 0.03);
                    color: rgba(255, 255, 255, 0.6);
                    border-radius: 6px;
                    font-size: 10.5px;
                    font-weight: 500;
                    cursor: pointer;
                    transition: all 0.15s ease;
                }
                .teach-btn:hover {
                    background: rgba(255, 255, 255, 0.08);
                    color: #ffffff;
                    border-color: rgba(255, 255, 255, 0.16);
                }
                .teach-btn:active {
                    transform: scale(0.97);
                }
                .teach-btn-discard {
                    color: rgba(255, 255, 255, 0.5);
                }
                .teach-btn-discard:hover {
                    background: rgba(239, 68, 68, 0.12);
                    color: #f87171;
                    border-color: rgba(239, 68, 68, 0.28);
                }
                .teach-btn-finish {
                    display: flex;
                    align-items: center;
                    gap: 5px;
                    height: 26px;
                    padding: 0 11px;
                    border: 1px solid rgba(16, 185, 129, 0.4);
                    background: linear-gradient(180deg, rgba(16, 185, 129, 0.22) 0%, rgba(5, 150, 105, 0.30) 100%);
                    color: #6ee7b7;
                    border-radius: 6px;
                    font-size: 11px;
                    font-weight: 600;
                    cursor: pointer;
                    box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.1) inset, 0 2px 6px rgba(0, 0, 0, 0.35);
                    transition: all 0.15s ease;
                }
                .teach-btn-finish:hover {
                    background: linear-gradient(180deg, rgba(16, 185, 129, 0.35) 0%, rgba(5, 150, 105, 0.45) 100%);
                    border-color: rgba(52, 211, 153, 0.6);
                    color: #a7f3d0;
                }
                .teach-btn-finish:active {
                    transform: scale(0.97);
                }

                #chevron-svg {
                    transition: transform 0.2s ease;
                }
                #chevron-svg.open {
                    transform: rotate(180deg);
                }

                /* Steps drawer */
                #nexus-teach-drawer {
                    width: 100%;
                    margin-top: 6px;
                    background: rgba(12, 13, 18, 0.96);
                    backdrop-filter: blur(28px);
                    -webkit-backdrop-filter: blur(28px);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 10px;
                    overflow: hidden;
                    box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 16px 40px rgba(0, 0, 0, 0.75);
                }
                .drawer-header {
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    padding: 7px 12px;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.06);
                    font-size: 10px;
                    font-weight: 600;
                    color: rgba(255, 255, 255, 0.45);
                    text-transform: uppercase;
                    letter-spacing: 0.08em;
                }
                #nexus-teach-steps-list {
                    max-height: 200px;
                    overflow-y: auto;
                    padding: 6px 8px;
                    display: flex;
                    flex-direction: column;
                    gap: 3px;
                }
                #nexus-teach-steps-list::-webkit-scrollbar {
                    width: 4px;
                }
                #nexus-teach-steps-list::-webkit-scrollbar-thumb {
                    background: rgba(255, 255, 255, 0.15);
                    border-radius: 4px;
                }

                .empty-steps-hint {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    gap: 8px;
                    padding: 14px 0;
                    font-size: 11px;
                    color: rgba(255, 255, 255, 0.40);
                }
                .pulse-indicator {
                    width: 5px;
                    height: 5px;
                    border-radius: 50%;
                    background: #94a3b8;
                    animation: recPulse 1.4s infinite;
                }

                .step-item {
                    display: flex;
                    align-items: center;
                    gap: 8px;
                    padding: 5px 8px;
                    border-radius: 6px;
                    background: rgba(255, 255, 255, 0.02);
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    font-size: 11px;
                    transition: background 0.15s;
                }
                .step-item:last-child {
                    background: rgba(255, 255, 255, 0.05);
                    border-color: rgba(255, 255, 255, 0.12);
                }
                .step-num {
                    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
                    font-size: 9.5px;
                    color: rgba(255, 255, 255, 0.35);
                    width: 14px;
                    text-align: center;
                    flex-shrink: 0;
                }
                .step-icon {
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: rgba(255, 255, 255, 0.7);
                    flex-shrink: 0;
                }
                .step-text {
                    flex: 1 1 0%;
                    min-width: 0;
                    display: flex;
                    align-items: baseline;
                    gap: 5px;
                    overflow: hidden;
                }
                .step-label {
                    font-weight: 600;
                    color: #e2e8f0;
                    flex-shrink: 0;
                    font-size: 10.5px;
                }
                .step-desc {
                    color: rgba(255, 255, 255, 0.55);
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                    font-size: 10.5px;
                }
                .step-badge {
                    font-size: 8.5px;
                    font-weight: 600;
                    text-transform: uppercase;
                    letter-spacing: 0.06em;
                    padding: 1px 5px;
                    background: rgba(255, 255, 255, 0.08);
                    color: rgba(255, 255, 255, 0.75);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 4px;
                    flex-shrink: 0;
                }
            </style>

            <div id="teach-container">
                <div id="teach-banner">
                    <!-- REC badge -->
                    <div class="rec-badge" id="rec-badge">
                        <span class="rec-dot" id="rec-dot"></span>
                        <span id="rec-timer-label">REC 00:00</span>
                    </div>

                    <!-- Environment badge -->
                    <div class="env-badge">
                        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                        <span>Browser</span>
                    </div>

                    <!-- Content -->
                    <div class="teach-content">
                        <div class="teach-title-row">
                            <span class="teach-prompt-title" id="teach-prompt-title">${promptText || "Recording Workflow…"}</span>
                            <span class="teach-steps-pill" id="teach-steps-pill" style="display:none;">0 steps</span>
                        </div>
                        <div class="teach-sub-action" id="teach-sub-action">Listening for clicks & typing in Chrome…</div>
                    </div>

                    <!-- Actions -->
                    <div class="teach-actions">
                        <button class="teach-btn" id="btn-expand" title="Show recorded steps list">
                            <svg id="chevron-svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>
                        <button class="teach-btn" id="btn-pause" title="Pause / Resume recording">
                            <svg id="pause-svg" width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                            <svg id="play-svg" width="10" height="10" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        </button>
                        <button class="teach-btn teach-btn-discard" id="btn-discard" title="Discard recording">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                        </button>
                        <button class="teach-btn-finish" id="btn-finish" title="Finish demonstration and review skill">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
                            <span>Finish</span>
                        </button>
                    </div>
                </div>

                <!-- Steps Drawer -->
                <div id="nexus-teach-drawer" style="display:none;">
                    <div class="drawer-header">
                        <span>Recorded Steps</span>
                        <span id="drawer-counter">0 actions</span>
                    </div>
                    <div id="nexus-teach-steps-list">
                        <div class="empty-steps-hint">
                            <span class="pulse-indicator"></span>
                            <span>Waiting for your interactions in Chrome…</span>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.documentElement.appendChild(hostEl);

        const btnExpand = shadow.getElementById("btn-expand");
        const btnPause = shadow.getElementById("btn-pause");
        const btnFinish = shadow.getElementById("btn-finish");
        const btnDiscard = shadow.getElementById("btn-discard");
        const drawer = shadow.getElementById("nexus-teach-drawer");
        const chevron = shadow.getElementById("chevron-svg");

        btnExpand.addEventListener("click", () => {
            isDrawerOpen = !isDrawerOpen;
            if (drawer) drawer.style.display = isDrawerOpen ? "block" : "none";
            if (chevron) {
                if (isDrawerOpen) chevron.classList.add("open");
                else chevron.classList.remove("open");
            }
        });

        btnPause.addEventListener("click", () => {
            if (isPaused) {
                nexusTeachHUD.setPaused(false);
            } else {
                nexusTeachHUD.setPaused(true);
            }
        });

        btnFinish.addEventListener("click", () => {
            nexusTeachHUD.finish();
        });

        btnDiscard.addEventListener("click", () => {
            nexusTeachHUD.discard();
        });
    }

    function updateTimer() {
        if (!shadow || isPaused) return;
        elapsedSeconds++;
        const m = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
        const s = String(elapsedSeconds % 60).padStart(2, "0");
        const el = shadow.getElementById("rec-timer-label");
        if (el) el.textContent = `REC ${m}:${s}`;
    }

    return {
        start(payload) {
            isRecording = true;
            isPaused = Boolean(payload?.is_paused);
            currentSessionId = payload?.session_id || `teach-${Date.now()}`;
            currentPrompt = payload?.prompt || "";

            if (payload?.elapsed_seconds !== undefined) {
                elapsedSeconds = Number(payload.elapsed_seconds) || 0;
            } else if (!payload?.resume) {
                elapsedSeconds = 0;
            }

            if (Array.isArray(payload?.actions) && payload.actions.length > 0) {
                recordedActions = [...payload.actions];
            } else if (!payload?.resume) {
                recordedActions = [];
            }

            // Universal OS Pill: The desktop floating pill window is the primary HUD outside the browser.
            // Only render an in-page DOM overlay if explicitly requested.
            if (payload?.render_in_page_hud === true) {
                renderHUD(currentPrompt);
            }
            attachListeners();

            if (timerInterval) clearInterval(timerInterval);
            timerInterval = setInterval(updateTimer, 1000);

            // Sync visual elements immediately after rendering
            if (shadow) {
                const m = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
                const s = String(elapsedSeconds % 60).padStart(2, "0");
                const timerLabel = shadow.getElementById("rec-timer-label");
                if (timerLabel) timerLabel.textContent = `${isPaused ? "PAUSED" : "REC"} ${m}:${s}`;

                const banner = shadow.getElementById("teach-banner");
                const badge = shadow.getElementById("rec-badge");
                const dot = shadow.getElementById("rec-dot");
                const pauseSvg = shadow.getElementById("pause-svg");
                const playSvg = shadow.getElementById("play-svg");

                if (isPaused) {
                    if (banner) banner.classList.add("paused");
                    if (badge) badge.classList.add("paused");
                    if (dot) dot.classList.add("paused");
                    if (pauseSvg) pauseSvg.style.display = "none";
                    if (playSvg) playSvg.style.display = "block";
                }

                if (recordedActions.length > 0) {
                    const pillCount = shadow.getElementById("teach-steps-pill");
                    if (pillCount) {
                        pillCount.textContent = `${recordedActions.length} step${recordedActions.length !== 1 ? "s" : ""}`;
                        pillCount.style.display = "inline-flex";
                    }

                    const subAction = shadow.getElementById("teach-sub-action");
                    if (subAction) {
                        subAction.textContent = recordedActions[recordedActions.length - 1].desc;
                    }

                    const drawerCount = shadow.getElementById("drawer-counter");
                    if (drawerCount) {
                        drawerCount.textContent = `${recordedActions.length} action${recordedActions.length !== 1 ? "s" : ""}`;
                    }

                    const stepsList = shadow.getElementById("nexus-teach-steps-list");
                    if (stepsList) {
                        const emptyHint = stepsList.querySelector(".empty-steps-hint");
                        if (emptyHint) emptyHint.remove();
                        stepsList.innerHTML = "";
                        recordedActions.forEach((actionObj, i) => {
                            const item = document.createElement("div");
                            item.className = "step-item";
                            const isLatest = i === recordedActions.length - 1;
                            item.innerHTML = `
                                <span class="step-num">${i + 1}</span>
                                <span class="step-icon">${getActionIconSVG(actionObj.type)}</span>
                                <div class="step-text">
                                    <span class="step-label">${actionObj.label}</span>
                                    <span class="step-desc">${actionObj.sub || actionObj.desc}</span>
                                </div>
                                ${isLatest ? '<span class="step-badge">latest</span>' : ''}
                            `;
                            stepsList.appendChild(item);
                        });
                        stepsList.scrollTop = stepsList.scrollHeight;
                    }
                }
            }

            if (!payload?.resume) {
                sendTeachEvent("navigate", null, {
                    value: window.location.href,
                    metadata: { title: document.title }
                });
            }

            return { success: true, session_id: currentSessionId };
        },

        setPaused(paused) {
            isPaused = paused;
            if (shadow) {
                const banner = shadow.getElementById("teach-banner");
                const badge = shadow.getElementById("rec-badge");
                const dot = shadow.getElementById("rec-dot");
                const timerLabel = shadow.getElementById("rec-timer-label");
                const pauseSvg = shadow.getElementById("pause-svg");
                const playSvg = shadow.getElementById("play-svg");

                if (isPaused) {
                    if (banner) banner.classList.add("paused");
                    if (badge) badge.classList.add("paused");
                    if (dot) dot.classList.add("paused");
                    const m = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
                    const s = String(elapsedSeconds % 60).padStart(2, "0");
                    if (timerLabel) timerLabel.textContent = `PAUSED ${m}:${s}`;
                    if (pauseSvg) pauseSvg.style.display = "none";
                    if (playSvg) playSvg.style.display = "block";
                } else {
                    if (banner) banner.classList.remove("paused");
                    if (badge) badge.classList.remove("paused");
                    if (dot) dot.classList.remove("paused");
                    const m = String(Math.floor(elapsedSeconds / 60)).padStart(2, "0");
                    const s = String(elapsedSeconds % 60).padStart(2, "0");
                    if (timerLabel) timerLabel.textContent = `REC ${m}:${s}`;
                    if (pauseSvg) pauseSvg.style.display = "block";
                    if (playSvg) playSvg.style.display = "none";
                }
            }
            try {
                chrome.runtime.sendMessage({
                    type: "teach_action",
                    action: isPaused ? "pause" : "resume",
                    session_id: currentSessionId
                });
            } catch (_) {}
            return { success: true, is_paused: isPaused };
        },

        finish() {
            detachListeners();
            if (timerInterval) clearInterval(timerInterval);
            const sId = currentSessionId;
            if (hostEl) {
                hostEl.remove();
                hostEl = null;
                shadow = null;
            }
            const stray = document.getElementById("nexus-teach-hud-root");
            if (stray) stray.remove();
            isRecording = false;

            // ⚡ Instant 0ms wakeup: signal Spotlight window to appear immediately
            try {
                fetch("http://127.0.0.1:8765/show-spotlight", { method: "POST" }).catch(() => {});
            } catch (_) {}

            // Direct local loopback HTTP call to backend (0ms latency fallback)
            try {
                fetch("http://127.0.0.1:8000/api/skills/teach/stop-direct", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ session_id: sId })
                }).catch(() => {});
            } catch (_) {}

            try {
                chrome.runtime.sendMessage({
                    type: "teach_action",
                    action: "finish",
                    session_id: sId
                });
            } catch (_) {}
            return { success: true };
        },

        discard() {
            detachListeners();
            if (timerInterval) clearInterval(timerInterval);
            const sId = currentSessionId;
            if (hostEl) {
                hostEl.remove();
                hostEl = null;
                shadow = null;
            }
            const stray = document.getElementById("nexus-teach-hud-root");
            if (stray) stray.remove();
            isRecording = false;
            try {
                chrome.runtime.sendMessage({
                    type: "teach_action",
                    action: "discard",
                    session_id: sId
                });
            } catch (_) {}
            return { success: true };
        },

        stop() {
            detachListeners();
            if (timerInterval) clearInterval(timerInterval);
            if (hostEl) {
                hostEl.remove();
                hostEl = null;
                shadow = null;
            }
            const stray = document.getElementById("nexus-teach-hud-root");
            if (stray) stray.remove();
            isRecording = false;
            return { success: true };
        }
    };
})();

// ─────────────────────────────────────────────────────────────────────────────
// NEXUS Automation Overlay
// Injected into a Shadow DOM root to avoid any CSS conflicts with the host page.
// ─────────────────────────────────────────────────────────────────────────────
const nexusOverlay = (() => {
    const OVERLAY_HTML = `

        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }

            #nexus-overlay {
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                width: 100vw;
                height: 0 !important;
                max-height: 0 !important;
                z-index: 2147483647;
                pointer-events: none !important;
                background: transparent !important;
                backdrop-filter: none !important;
                -webkit-backdrop-filter: none !important;
                display: flex;
                align-items: flex-start;
                justify-content: center;
                padding-top: 16px;
                font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
                transition: opacity 0.2s ease;
                opacity: 0;
                cursor: default !important;
                user-select: none !important;
                -webkit-user-select: none !important;
                overflow: visible !important;
            }
            #nexus-overlay.visible { opacity: 1; pointer-events: none !important; }
            #nexus-overlay.paused { background: transparent !important; cursor: default !important; }

            /* Overlay is a floating non-blocking pill; underlying page is always interactive */
            #nexus-overlay.shield-disabled {
                pointer-events: none !important;
                background: transparent !important;
                backdrop-filter: none !important;
                -webkit-backdrop-filter: none !important;
                cursor: default !important;
            }

            #nexus-widget {
                display: flex;
                flex-direction: column;
                align-items: center;
                width: 540px !important;
                min-width: 540px !important;
                max-width: 540px !important;
                pointer-events: all !important;
                cursor: default !important;
                font-family: 'Inter', -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, sans-serif;
            }


            #nexus-banner {
                position: relative;
                width: 540px !important;
                min-width: 540px !important;
                max-width: 540px !important;
                box-sizing: border-box !important;
                display: flex;
                align-items: center;
                gap: 10px;
                background: rgba(10, 11, 15, 0.94);
                backdrop-filter: blur(24px) saturate(180%);
                -webkit-backdrop-filter: blur(24px) saturate(180%);
                border: 1px solid rgba(255, 255, 255, 0.09);
                border-radius: 12px;
                padding: 6px 12px;
                box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.06) inset, 0 16px 36px -4px rgba(0, 0, 0, 0.75);
                pointer-events: all !important;
                user-select: none;
                transition: border-color 0.2s ease, box-shadow 0.2s ease;
            }

            #nexus-banner.paused {
                border-color: rgba(245, 158, 11, 0.35);
            }

            /* Logo mark */
            .nexus-logo {
                width: 24px;
                height: 24px;
                border-radius: 7px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                display: flex;
                align-items: center;
                justify-content: center;
                flex-shrink: 0;
                color: #38bdf8;
            }

            .nexus-content {
                flex: 1 1 0%;
                min-width: 0;
                overflow: hidden;
                cursor: default;
            }

            .nexus-header {
                display: flex;
                align-items: center;
                gap: 7px;
                margin-bottom: 2px;
            }

            #nexus-status {
                font-size: 10px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: rgba(255, 255, 255, 0.5);
            }
            #nexus-status.paused { color: #fbbf24; }

            /* Animated dot */
            .nexus-dot {
                width: 5px;
                height: 5px;
                border-radius: 50%;
                background: #38bdf8;
                box-shadow: 0 0 8px rgba(56, 189, 248, 0.6);
                flex-shrink: 0;
                animation: nexus-pulse 1.4s ease-in-out infinite;
            }
            .nexus-dot.paused {
                background: #fbbf24;
                box-shadow: 0 0 8px rgba(251, 191, 36, 0.6);
                animation: none;
            }

            #nexus-step {
                font-size: 12px;
                font-weight: 500;
                color: rgba(255, 255, 255, 0.88);
                white-space: nowrap;
                overflow: hidden;
                text-overflow: ellipsis;
                display: block;
                width: 100%;
                cursor: default;
            }

            /* Tooltip on hover showing full text without changing pill width */
            .nexus-step-tooltip {
                display: none;
                position: absolute;
                top: calc(100% + 8px);
                left: 0;
                width: 540px !important;
                box-sizing: border-box !important;
                background: radial-gradient(ellipse 90% 60% at 50% -15%, rgba(56, 189, 248, 0.04), transparent 70%), #101116;
                border: 1px solid rgba(255, 255, 255, 0.12);
                border-radius: 12px;
                padding: 10px 14px;
                color: #f1f5f9;
                font-size: 11px;
                line-height: 1.45;
                white-space: normal;
                word-break: break-word;
                box-shadow: 0 12px 36px rgba(0, 0, 0, 0.88);
                z-index: 2147483647;
                pointer-events: none;
            }

            .nexus-content:hover ~ .nexus-step-tooltip {
                display: block !important;
            }

            #nexus-step-count {
                font-size: 10px;
                font-weight: 500;
                font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
                color: rgba(255, 255, 255, 0.35);
                flex-shrink: 0;
                margin-right: 4px;
            }

            /* Controls on right side of banner */
            .nexus-actions {
                display: flex;
                align-items: center;
                gap: 4px;
                flex-shrink: 0;
            }

            .nexus-btn {
                display: inline-flex;
                align-items: center;
                justify-content: center;
                gap: 4px;
                height: 24px;
                min-width: 24px;
                padding: 0 7px;
                border-radius: 7px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.08);
                color: rgba(255, 255, 255, 0.70);
                cursor: pointer;
                font-size: 10.5px;
                font-weight: 500;
                transition: all 0.15s ease;
                user-select: none;
            }
            .nexus-btn:hover {
                background: rgba(255, 255, 255, 0.09);
                color: #fff;
                border-color: rgba(255, 255, 255, 0.14);
            }
            .nexus-btn:active {
                transform: scale(0.96);
            }

            .nexus-btn-error {
                background: rgba(239, 68, 68, 0.12);
                border-color: rgba(239, 68, 68, 0.25);
                color: #fca5a5;
            }
            .nexus-btn-error:hover {
                background: rgba(239, 68, 68, 0.20);
                color: #fee2e2;
                border-color: rgba(239, 68, 68, 0.40);
            }

            /* Hairline progress bar */
            #nexus-progress-track {
                height: 1.5px;
                background: rgba(255, 255, 255, 0.06);
                border-radius: 9999px;
                overflow: hidden;
                margin-top: 5px;
            }
            #nexus-progress-fill {
                height: 100%;
                background: linear-gradient(90deg, #38bdf8, #818cf8);
                border-radius: 9999px;
                width: 0%;
                transition: width 0.3s ease;
            }
            #nexus-progress-fill.indeterminate {
                width: 35%;
                animation: nexus-slide 1.4s ease-in-out infinite;
            }

            /* Expandable Steps Drawer */
            #nexus-steps-drawer {
                width: 100%;
                margin-top: 6px;
                background: radial-gradient(ellipse 90% 60% at 50% -15%, rgba(56, 189, 248, 0.03), transparent 70%), #101116;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 14px;
                padding: 10px 14px;
                box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.08) inset, 0 12px 36px rgba(0, 0, 0, 0.75);
                max-height: 240px;
                overflow-y: auto;
                pointer-events: all !important;
            }

            .nexus-step-item {
                display: flex;
                align-items: flex-start;
                gap: 8px;
                padding: 5px 8px;
                border-radius: 7px;
                font-size: 11px;
                line-height: 1.35;
                color: rgba(255, 255, 255, 0.65);
                margin-bottom: 2px;
                transition: background 0.12s ease;
            }
            .nexus-step-item.running {
                background: rgba(56, 189, 248, 0.10);
                color: #fff;
                font-weight: 500;
                border: 1px solid rgba(56, 189, 248, 0.20);
            }
            .nexus-step-item.completed {
                color: rgba(255, 255, 255, 0.4);
            }
            .nexus-step-item.failed {
                background: rgba(239, 68, 68, 0.12);
                color: #fca5a5;
                border: 1px solid rgba(239, 68, 68, 0.25);
            }

            /* Error detail drawer */
            #nexus-error-drawer {
                width: 100%;
                margin-top: 6px;
                background: rgba(20, 10, 14, 0.98);
                border: 1px solid rgba(239, 68, 68, 0.25);
                border-radius: 14px;
                padding: 10px 14px;
                color: #fecaca;
                font-size: 11px;
                line-height: 1.4;
                box-shadow: 0 12px 36px rgba(0, 0, 0, 0.8);
                pointer-events: all !important;
            }
            .nexus-error-title {
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: #f87171;
                margin-bottom: 4px;
            }

            /* Interactive Input / Choice Drawer */
            #nexus-input-drawer {
                width: 100%;
                margin-top: 6px;
                background: radial-gradient(ellipse 90% 60% at 50% -15%, rgba(56, 189, 248, 0.05), transparent 70%), #101116;
                border: 1px solid rgba(56, 189, 248, 0.25);
                border-radius: 14px;
                padding: 12px 14px;
                box-shadow: 0 1px 0 0 rgba(255, 255, 255, 0.08) inset, 0 12px 36px rgba(0, 0, 0, 0.8), 0 0 20px rgba(56, 189, 248, 0.10);
                pointer-events: all !important;
                cursor: default !important;
            }
            .nexus-input-header {
                display: flex;
                align-items: center;
                gap: 6px;
                font-size: 11.5px;
                font-weight: 600;
                color: #f0f9ff;
                margin-bottom: 10px;
            }
            .nexus-input-options {
                display: flex;
                flex-wrap: wrap;
                gap: 6px;
                margin-bottom: 10px;
            }
            .nexus-choice-chip {
                padding: 4px 12px;
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 20px;
                color: rgba(255, 255, 255, 0.85);
                font-size: 11px;
                font-weight: 500;
                cursor: pointer;
                transition: all 0.15s ease;
                user-select: none;
            }
            .nexus-choice-chip:hover {
                background: rgba(56, 189, 248, 0.15);
                border-color: rgba(56, 189, 248, 0.4);
                color: #ffffff;
                box-shadow: 0 0 12px rgba(56, 189, 248, 0.2);
            }
            .nexus-input-form {
                display: flex;
                align-items: center;
                gap: 6px;
            }
            #nexus-input-field {
                flex: 1;
                height: 30px;
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(255, 255, 255, 0.10);
                border-radius: 7px;
                padding: 0 10px;
                color: #ffffff;
                font-size: 11.5px;
                outline: none;
                font-family: inherit;
                transition: border-color 0.15s ease, box-shadow 0.15s ease;
                cursor: text !important;
                user-select: text !important;
                -webkit-user-select: text !important;
            }

            #nexus-input-field:focus {
                border-color: #38bdf8;
                box-shadow: 0 0 0 2px rgba(56, 189, 248, 0.2);
            }
            #nexus-input-submit {
                height: 30px;
                padding: 0 14px;
                background: #0284c7;
                border: 1px solid rgba(56, 189, 248, 0.4);
                border-radius: 7px;
                color: #ffffff;
                font-size: 11px;
                font-weight: 600;
                cursor: pointer;
                transition: all 0.15s ease;
                user-select: none;
            }
            #nexus-input-submit:hover {
                background: #0369a1;
            }

            /* Multi-issue drawer styling */
            #nexus-error-drawer {
                width: 100%;
                margin-top: 6px;
                background: rgba(24, 10, 12, 0.98);
                border: 1px solid rgba(239, 68, 68, 0.35);
                border-radius: 10px;
                padding: 10px 14px;
                color: #fecaca;
                font-size: 11px;
                line-height: 1.4;
                box-shadow: 0 12px 36px rgba(0, 0, 0, 0.8);
                max-height: 250px;
                overflow-y: auto;
                pointer-events: all !important;
                cursor: default !important;
            }
            .nexus-error-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 8px;
                padding-bottom: 6px;
                border-bottom: 1px solid rgba(239, 68, 68, 0.2);
            }
            .nexus-error-title {
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                color: #f87171;
            }
            .nexus-error-list {
                display: flex;
                flex-direction: column;
                gap: 6px;
            }
            .nexus-issue-card {
                background: rgba(239, 68, 68, 0.08);
                border: 1px solid rgba(239, 68, 68, 0.2);
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 11px;
            }
            .nexus-issue-meta {
                display: flex;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 3px;
            }
            .nexus-issue-badge {
                font-size: 9px;
                font-weight: 700;
                text-transform: uppercase;
                background: rgba(239, 68, 68, 0.25);
                color: #fca5a5;
                padding: 1px 5px;
                border-radius: 4px;
            }
            .nexus-issue-time {
                font-size: 9px;
                font-family: monospace;
                color: rgba(255, 255, 255, 0.4);
            }
            .nexus-issue-text {
                color: #fecaca;
                word-break: break-word;
                font-family: inherit;
            }

            @keyframes nexus-pulse {
                0%, 100% { opacity: 1; transform: scale(1); }
                50% { opacity: 0.3; transform: scale(0.8); }
            }
            @keyframes nexus-slide {
                0% { transform: translateX(-150%); }
                100% { transform: translateX(350%); }
            }
        </style>

        <div id="nexus-overlay">
            <div id="nexus-widget">
                <div id="nexus-banner">
                    <div class="nexus-logo">
                        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                            <polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>
                            <polyline points="2 17 12 22 22 17"></polyline>
                            <polyline points="2 12 12 17 22 12"></polyline>
                        </svg>
                    </div>
                    <div class="nexus-content">
                        <div class="nexus-header">
                            <span id="nexus-status">Automating</span>
                            <div class="nexus-dot" id="nexus-dot"></div>
                        </div>
                        <div id="nexus-step">Initializing...</div>
                        <div id="nexus-progress-track">
                            <div id="nexus-progress-fill" class="indeterminate"></div>
                        </div>
                    </div>
                    <div id="nexus-step-count"></div>
                    <div class="nexus-actions">
                        <button id="nexus-btn-error" class="nexus-btn nexus-btn-error" style="display:none;" title="View Issues">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
                            <span>Issues (<span id="nexus-error-badge-count">0</span>)</span>
                        </button>
                        <button id="nexus-btn-pause" class="nexus-btn" title="Pause / Resume">
                            <svg id="nexus-icon-pause" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg>
                            <svg id="nexus-icon-play" width="11" height="11" viewBox="0 0 24 24" fill="currentColor" style="display:none;"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                        </button>
                        <button id="nexus-btn-expand" class="nexus-btn" title="Toggle Steps List">
                            <svg id="nexus-icon-chevron" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>
                        <button id="nexus-btn-close" class="nexus-btn" title="Dismiss / Quit Pill">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                        </button>
                    </div>
                    <div id="nexus-step-tooltip" class="nexus-step-tooltip"></div>
                </div>

                <div id="nexus-input-drawer" style="display:none;">
                    <div class="nexus-input-header">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                        <span id="nexus-input-prompt" style="flex:1;">Input requested</span>
                        <button id="nexus-input-speak" type="button" class="nexus-btn" title="Read question aloud" style="height:20px;padding:0 6px;font-size:10px;margin-left:auto;">
                            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/></svg>
                            <span>Listen</span>
                        </button>
                    </div>
                    <div id="nexus-input-options" class="nexus-input-options"></div>
                    <div class="nexus-input-form">
                        <input id="nexus-input-field" type="text" placeholder="Type or speak response..." autocomplete="off" />
                        <button id="nexus-input-mic" type="button" class="nexus-btn" title="Speak your response" style="height:28px;padding:0 8px;background:rgba(255,255,255,0.08);border-color:rgba(255,255,255,0.2);">
                            <svg id="nexus-mic-svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/></svg>
                        </button>
                        <button id="nexus-input-submit" type="button">Submit</button>
                    </div>
                    <div id="nexus-input-voice-indicator" style="display:none;font-size:10px;color:#f87171;margin-top:5px;align-items:center;gap:5px;">
                        <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:#ef4444;animation:nexus-pulse 1s infinite;"></span>
                        <span>Listening... speak your response</span>
                    </div>
                </div>

                <div id="nexus-steps-drawer" style="display:none;">
                    <div id="nexus-steps-list"></div>
                </div>

                <div id="nexus-error-drawer" style="display:none;">
                    <div class="nexus-error-header">
                        <span class="nexus-error-title">Runtime Issues & Notices (<span id="nexus-error-count-title">0</span>)</span>
                    </div>
                    <div id="nexus-error-list" class="nexus-error-list"></div>
                </div>
            </div>
        </div>
    `;


    const BLOCK_EVENTS = [
        'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick',
        'contextmenu', 'touchstart', 'touchend', 'touchmove', 'keydown', 'keyup', 'keypress', 'wheel'
    ];

    let _host = null;
    let _shadow = null;
    let _overlay = null;
    let _stepEl = null;
    let _statusEl = null;
    let _progressEl = null;
    let _stepCountEl = null;
    let _steps = [];
    let _issues = [];
    let _isPaused = false;
    let _stepsDrawerOpen = false;
    let _errorDrawerOpen = false;

    function _disableShield() {
        if (_overlay) {
            _overlay.classList.add("shield-disabled");
        }
    }

    function _enableShield() {
        if (_overlay) {
            _overlay.classList.remove("shield-disabled");
        }
    }

    function _addIssue({ type = "runtime", message = "", timestamp = null } = {}) {
        if (!message) return;
        const ts = timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const existing = _issues.find(i => i.message === message);
        if (existing) {
            existing.count = (existing.count || 1) + 1;
            existing.timestamp = ts;
        } else {
            _issues.push({ type, message, timestamp: ts, count: 1 });
        }
        _updateIssuesUI();
        // An issue occurred — immediately release full-screen shield so user can interact with page
        _disableShield();
    }

    function _updateIssuesUI() {
        if (!_shadow) return;
        const errBtn = _shadow.getElementById("nexus-btn-error");
        const countBadge = _shadow.getElementById("nexus-error-badge-count");
        const countTitle = _shadow.getElementById("nexus-error-count-title");
        const totalCount = _issues.length;

        if (countBadge) countBadge.textContent = String(totalCount);
        if (countTitle) countTitle.textContent = String(totalCount);
        if (errBtn) {
            errBtn.style.display = totalCount > 0 ? "inline-flex" : "none";
        }
        _renderIssues();
    }

    function _renderIssues() {
        if (!_shadow) return;
        const listEl = _shadow.getElementById("nexus-error-list");
        if (!listEl) return;
        if (!_issues || _issues.length === 0) {
            listEl.innerHTML = '<div style="font-size:11px;color:rgba(255,255,255,0.4);padding:4px 6px;">No issues reported</div>';
            return;
        }
        let html = "";
        _issues.forEach((item) => {
            const countTag = item.count > 1 ? ` <span style="opacity:0.65;">(x${item.count})</span>` : "";
            html += `<div class="nexus-issue-card">
                <div class="nexus-issue-meta">
                    <span class="nexus-issue-badge">${item.type || 'NOTICE'}</span>
                    <span class="nexus-issue-time">${item.timestamp || ''}</span>
                </div>
                <div class="nexus-issue-text">${item.message}${countTag}</div>
            </div>`;
        });
        listEl.innerHTML = html;
    }

    function _blockInteraction(e) {
        // Non-blocking HUD: allow all mouse, pointer, and keyboard events to reach the webpage uninterrupted
        return;
    }

    function _renderStepsList() {
        if (!_shadow) return;
        const listEl = _shadow.getElementById("nexus-steps-list");
        if (!listEl) return;
        if (!_steps || _steps.length === 0) {
            listEl.innerHTML = '<div style="font-size:11px;color:rgba(255,255,255,0.4);padding:4px 6px;">No steps available</div>';
            return;
        }
        let html = "";
        _steps.forEach((s, idx) => {
            const status = s.status || "pending";
            const title = s.title || s.description || `Step ${idx + 1}`;
            let icon = `<span style="width:12px;height:12px;display:inline-flex;align-items:center;justify-content:center;opacity:0.35;">•</span>`;
            if (status === "completed") {
                icon = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>`;
            } else if (status === "running") {
                icon = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.5" class="nexus-spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg>`;
            } else if (status === "failed") {
                icon = `<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="3"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
            }
            html += `<div class="nexus-step-item ${status}">
                <span style="flex-shrink:0;display:inline-flex;align-items:center;margin-top:1px;">${icon}</span>
                <span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${title}">${title}</span>
            </div>`;
        });
        listEl.innerHTML = html;
    }

    function _ensureDOM() {
        // Overlay disabled: In-page pill overlay is suppressed in favor of OS desktop floating pill
        try {
            const existingRoots = document.querySelectorAll("#__nexus-overlay-root__, #nexus-widget, #nexus-overlay");
            existingRoots.forEach(el => {
                try { el.remove(); } catch (_) {}
            });
            if (_host) {
                try { _host.remove(); } catch (_) {}
                _host = null;
                _shadow = null;
                _overlay = null;
            }
        } catch (_) {}
        return false;
    }

    function _disabledEnsureDOM() {

        if (_host && document.documentElement.contains(_host)) return;
        if (_host) {
            try { _host.remove(); } catch (_) {}
            _host = null;
        }

        _host = document.createElement("div");
        _host.id = "__nexus-overlay-root__";
        _host.style.cssText = "position:fixed !important;top:0 !important;left:0 !important;width:100vw !important;height:0 !important;max-height:0 !important;z-index:2147483647 !important;pointer-events:none !important;margin:0 !important;padding:0 !important;overflow:visible !important;";
        (document.body || document.documentElement).appendChild(_host);

        _shadow = _host.attachShadow({ mode: "open" });
        _shadow.innerHTML = OVERLAY_HTML;

        _overlay = _shadow.getElementById("nexus-overlay");
        _stepEl = _shadow.getElementById("nexus-step");
        _statusEl = _shadow.getElementById("nexus-status");
        _progressEl = _shadow.getElementById("nexus-progress-fill");
        _stepCountEl = _shadow.getElementById("nexus-step-count");

        // Wire interactive buttons inside shadow DOM
        const pauseBtn = _shadow.getElementById("nexus-btn-pause");
        if (pauseBtn) {
            pauseBtn.onclick = (e) => {
                e.stopPropagation();
                const next = !_isPaused;
                _setPaused(next);
                if (typeof chrome !== "undefined" && chrome?.runtime?.sendMessage) {
                    chrome.runtime.sendMessage({ action: next ? "pause_automation" : "pause_resume" });
                }
            };
        }

        const expandBtn = _shadow.getElementById("nexus-btn-expand");
        const stepsDrawer = _shadow.getElementById("nexus-steps-drawer");
        const chevronIcon = _shadow.getElementById("nexus-icon-chevron");
        if (expandBtn && stepsDrawer) {
            expandBtn.onclick = (e) => {
                e.stopPropagation();
                _stepsDrawerOpen = !_stepsDrawerOpen;
                stepsDrawer.style.display = _stepsDrawerOpen ? "block" : "none";
                if (chevronIcon) {
                    chevronIcon.style.transform = _stepsDrawerOpen ? "rotate(180deg)" : "rotate(0deg)";
                }
                if (_stepsDrawerOpen) {
                    _renderStepsList();
                }
            };
        }

        const errorBtn = _shadow.getElementById("nexus-btn-error");
        const errorDrawer = _shadow.getElementById("nexus-error-drawer");
        if (errorBtn && errorDrawer) {
            errorBtn.onclick = (e) => {
                e.stopPropagation();
                _errorDrawerOpen = !_errorDrawerOpen;
                errorDrawer.style.display = _errorDrawerOpen ? "block" : "none";
                if (_errorDrawerOpen) {
                    _renderIssues();
                }
            };
        }

        const closeBtn = _shadow.getElementById("nexus-btn-close");
        if (closeBtn) {
            closeBtn.onclick = (e) => {
                e.stopPropagation();
                hide({ message: "Overlay dismissed", delay: 0 });
                if (typeof chrome !== "undefined" && chrome?.runtime?.sendMessage) {
                    chrome.runtime.sendMessage({ action: "stop_automation" });
                }
            };
        }

        const inputField = _shadow.getElementById("nexus-input-field");
        const submitBtn = _shadow.getElementById("nexus-input-submit");
        const micBtn = _shadow.getElementById("nexus-input-mic");
        const speakBtn = _shadow.getElementById("nexus-input-speak");
        const voiceIndicator = _shadow.getElementById("nexus-input-voice-indicator");

        let _voiceRec = null;
        let _isRecActive = false;

        if (speakBtn) {
            speakBtn.onclick = (e) => {
                e.stopPropagation();
                const promptEl = _shadow?.getElementById("nexus-input-prompt");
                const textToSpeak = promptEl?.textContent || "";
                if (textToSpeak && typeof window !== "undefined" && window.speechSynthesis) {
                    window.speechSynthesis.cancel();
                    const u = new SpeechSynthesisUtterance(textToSpeak);
                    window.speechSynthesis.speak(u);
                }
            };
        }

        if (micBtn) {
            micBtn.onclick = (e) => {
                e.stopPropagation();
                if (_isRecActive) {
                    if (_voiceRec) {
                        try { _voiceRec.stop(); } catch (_) {}
                    }
                    _isRecActive = false;
                    micBtn.style.background = "rgba(255,255,255,0.08)";
                    micBtn.style.borderColor = "rgba(255,255,255,0.2)";
                    micBtn.style.color = "rgba(255,255,255,0.7)";
                    if (voiceIndicator) voiceIndicator.style.display = "none";
                    return;
                }

                const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
                if (!SpeechRec) {
                    alert("Speech recognition is not available in this browser window.");
                    return;
                }

                try {
                    const rec = new SpeechRec();
                    rec.continuous = false;
                    rec.interimResults = true;
                    rec.lang = "en-US";

                    rec.onstart = () => {
                        _isRecActive = true;
                        micBtn.style.background = "rgba(239, 68, 68, 0.25)";
                        micBtn.style.borderColor = "rgba(239, 68, 68, 0.6)";
                        micBtn.style.color = "#fca5a5";
                        if (voiceIndicator) voiceIndicator.style.display = "flex";
                    };

                    rec.onresult = (ev) => {
                        let str = "";
                        for (let i = ev.resultIndex; i < ev.results.length; i++) {
                            str += ev.results[i][0].transcript;
                        }
                        if (inputField && str) {
                            inputField.value = str;
                        }
                    };

                    rec.onerror = () => {
                        _isRecActive = false;
                        micBtn.style.background = "rgba(255,255,255,0.08)";
                        micBtn.style.borderColor = "rgba(255,255,255,0.2)";
                        micBtn.style.color = "rgba(255,255,255,0.7)";
                        if (voiceIndicator) voiceIndicator.style.display = "none";
                    };

                    rec.onend = () => {
                        _isRecActive = false;
                        micBtn.style.background = "rgba(255,255,255,0.08)";
                        micBtn.style.borderColor = "rgba(255,255,255,0.2)";
                        micBtn.style.color = "rgba(255,255,255,0.7)";
                        if (voiceIndicator) voiceIndicator.style.display = "none";
                    };

                    _voiceRec = rec;
                    rec.start();
                } catch (err) {
                    console.warn("SpeechRec error:", err);
                    _isRecActive = false;
                }
            };
        }

        if (inputField && submitBtn) {
            const doSubmit = () => {
                if (_isRecActive && _voiceRec) {
                    try { _voiceRec.stop(); } catch (_) {}
                    _isRecActive = false;
                }
                const val = (inputField.value || "").trim();
                if (val) {
                    _submitInput(val);
                }
            };
            submitBtn.onclick = (e) => {
                e.stopPropagation();
                doSubmit();
            };
            inputField.onkeydown = (e) => {
                e.stopPropagation();
                if (e.key === "Enter") {
                    e.preventDefault();
                    doSubmit();
                }
            };
        }

        // Overlay is non-blocking: no global event interception so native and synthetic clicks reach the DOM
    }

    function show({ task = "", step = "Starting automation...", step_index = null, total_steps = null, steps = null, error = null, issues = null } = {}) {
        _ensureDOM();
        _setPaused(false);
        const text = step || task || "Running...";
        if (_stepEl) {
            _stepEl.textContent = text;
            _stepEl.title = text;
        }
        const tooltip = _shadow?.getElementById("nexus-step-tooltip");
        if (tooltip) {
            tooltip.textContent = text;
        }
        _setProgress(step_index, total_steps);
        if (steps && Array.isArray(steps)) {
            _steps = steps;
        }
        if (Array.isArray(issues)) {
            issues.forEach(it => _addIssue(typeof it === 'string' ? { message: it } : it));
        }
        if (error) {
            _addIssue({ type: "error", message: error });
        }
        requestAnimationFrame(() => {
            if (_overlay) _overlay.classList.add("visible");
        });
        return { success: true };
    }

    function hide({ message = "All steps completed successfully", delay = 1800 } = {}) {
        if (!_overlay) return { success: true };

        // Release interaction lock so user can immediately use the page
        BLOCK_EVENTS.forEach(evt => {
            window.removeEventListener(evt, _blockInteraction, { capture: true, passive: false });
        });

        // Show proper success confirmation on banner
        if (_statusEl) {
            _statusEl.textContent = "Completed";
            _statusEl.style.color = "#34d399";
        }
        if (_stepEl) {
            _stepEl.textContent = message;
            _stepEl.title = message;
        }
        const tooltip = _shadow?.getElementById("nexus-step-tooltip");
        if (tooltip) {
            tooltip.textContent = message;
        }
        if (_progressEl) {
            _progressEl.classList.remove("indeterminate");
            _progressEl.style.width = "100%";
            _progressEl.style.background = "#10b981";
        }
        const dot = _shadow?.getElementById("nexus-dot");
        if (dot) {
            dot.style.background = "#10b981";
            dot.style.animation = "none";
        }

        // Gracefully fade out after delay
        setTimeout(() => {
            if (!_overlay) return;
            _overlay.classList.remove("visible");
            setTimeout(() => {
                if (_host) {
                    try { _host.remove(); } catch (_) {}
                    _host = null;
                    _shadow = null;
                    _overlay = null;
                    _stepsDrawerOpen = false;
                    _errorDrawerOpen = false;
                }
            }, 250);
        }, delay);

        return { success: true };
    }

    function setPaused(paused) {
        if (!_overlay) return { success: true, skipped: true };
        _setPaused(paused);
        return { success: true };
    }

    function _setPaused(paused) {
        _isPaused = !!paused;
        if (!_overlay) return;
        const banner = _shadow?.getElementById("nexus-banner");
        const dot = _shadow?.getElementById("nexus-dot");
        const pauseIcon = _shadow?.getElementById("nexus-icon-pause");
        const playIcon = _shadow?.getElementById("nexus-icon-play");

        if (_isPaused) {
            _overlay.classList.add("paused");
            if (banner) banner.classList.add("paused");
            if (_statusEl) {
                _statusEl.textContent = "Paused";
                _statusEl.classList.add("paused");
            }
            if (dot) dot.classList.add("paused");
            if (pauseIcon) pauseIcon.style.display = "none";
            if (playIcon) playIcon.style.display = "block";
            if (_progressEl) _progressEl.classList.remove("indeterminate");
        } else {
            _overlay.classList.remove("paused");
            if (banner) banner.classList.remove("paused");
            if (_statusEl) {
                _statusEl.textContent = "Automating";
                _statusEl.classList.remove("paused");
            }
            if (dot) dot.classList.remove("paused");
            if (pauseIcon) pauseIcon.style.display = "block";
            if (playIcon) playIcon.style.display = "none";
            if (_progressEl) _progressEl.classList.add("indeterminate");
        }
    }

    function updateStep({ step = "", step_index = null, total_steps = null, steps = null, error = null, issues = null } = {}) {
        if (!_overlay) return { success: true, skipped: true };
        const text = step || "Working...";
        if (_stepEl) {
            _stepEl.textContent = text;
            _stepEl.title = text;
        }
        const tooltip = _shadow?.getElementById("nexus-step-tooltip");
        if (tooltip) {
            tooltip.textContent = text;
        }
        _setProgress(step_index, total_steps);

        if (steps && Array.isArray(steps)) {
            _steps = steps;
            if (_stepsDrawerOpen) {
                _renderStepsList();
            }
        }

        if (Array.isArray(issues)) {
            issues.forEach(it => _addIssue(typeof it === 'string' ? { message: it } : it));
        }

        if (error) {
            _addIssue({ type: "error", message: error });
        } else if (step && /error|failed|rate limit|429/i.test(step)) {
            const isRateLimit = /rate limit|429/i.test(step);
            _addIssue({ type: isRateLimit ? "rate_limit" : "warning", message: step });
        }

        return { success: true };
    }

    function _setProgress(index, total) {
        if (!_progressEl) return;
        if (index != null && total != null && total > 0) {
            const pct = Math.round(((index + 1) / total) * 100);
            _progressEl.classList.remove("indeterminate");
            _progressEl.style.width = pct + "%";
            if (_stepCountEl) _stepCountEl.textContent = `${index + 1} / ${total}`;
        } else {
            _progressEl.classList.add("indeterminate");
            _progressEl.style.width = "";
            if (_stepCountEl) _stepCountEl.textContent = "";
        }
    }

    let _activeInputTaskId = null;

    function requestInput({ prompt = "Please provide your input:", options = [], placeholder = "Type your response...", task_id = null } = {}) {
        _ensureDOM();
        _activeInputTaskId = task_id;
        const inputDrawer = _shadow?.getElementById("nexus-input-drawer");
        const promptEl = _shadow?.getElementById("nexus-input-prompt");
        const optionsEl = _shadow?.getElementById("nexus-input-options");
        const inputField = _shadow?.getElementById("nexus-input-field");

        if (promptEl) promptEl.textContent = prompt;
        if (_stepEl) {
            _stepEl.textContent = prompt;
            _stepEl.title = prompt;
        }
        const tooltip = _shadow?.getElementById("nexus-step-tooltip");
        if (tooltip) {
            tooltip.textContent = prompt;
        }
        if (inputField) {
            inputField.placeholder = placeholder || "Type your response...";
            inputField.value = "";
        }

        if (optionsEl) {
            optionsEl.innerHTML = "";
            if (options && Array.isArray(options) && options.length > 0) {
                optionsEl.style.display = "flex";
                options.forEach(opt => {
                    const chip = document.createElement("button");
                    chip.className = "nexus-choice-chip";
                    chip.type = "button";
                    chip.onclick = (e) => {
                        e.stopPropagation();
                        _submitInput(opt);
                    };

                    const cleanOpt = String(opt).replace(/^[\u{1F300}-\u{1F9FF}\u{2600}-\u{27BF}\u{1F000}-\u{1FFFF}]\s*/u, '').trim();
                    const lower = cleanOpt.toLowerCase();

                    let iconSvg = "";
                    if (lower.includes("browse") || lower.includes("explorer") || lower.startsWith("desktop") || lower.startsWith("documents") || lower.includes("/") || lower.includes("\\")) {
                        iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#38bdf8" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>`;
                    } else if (lower.endsWith(".xlsx") || lower.endsWith(".xls") || lower.endsWith(".csv")) {
                        iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><path d="M8 13h8"></path><path d="M8 17h8"></path><path d="M10 9h4"></path></svg>`;
                    } else if (lower.endsWith(".docx") || lower.endsWith(".doc") || lower.endsWith(".txt") || lower.endsWith(".pdf")) {
                        iconSvg = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#60a5fa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" style="flex-shrink:0;"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`;
                    }

                    chip.innerHTML = `<span style="display:inline-flex;align-items:center;gap:5px;">${iconSvg}<span>${cleanOpt}</span></span>`;
                    optionsEl.appendChild(chip);
                });
            } else {
                optionsEl.style.display = "none";
            }
        }

        if (_statusEl) {
            _statusEl.textContent = "Input Needed";
            _statusEl.style.color = "#38bdf8";
        }
        const dot = _shadow?.getElementById("nexus-dot");
        if (dot) {
            dot.style.background = "#38bdf8";
            dot.style.animation = "nexus-pulse 1.4s ease-in-out infinite";
        }

        if (inputDrawer) {
            inputDrawer.style.display = "block";
        }

        requestAnimationFrame(() => {
            if (_overlay) _overlay.classList.add("visible");
            if (inputField) {
                setTimeout(() => inputField.focus(), 50);
            }
        });

        return { success: true };
    }

    function clearInput() {
        const inputDrawer = _shadow?.getElementById("nexus-input-drawer");
        if (inputDrawer) inputDrawer.style.display = "none";
        if (_statusEl && _statusEl.textContent === "Input Needed") {
            _statusEl.textContent = "Automating";
            _statusEl.style.color = "rgba(255, 255, 255, 0.5)";
        }
        const dot = _shadow?.getElementById("nexus-dot");
        if (dot) {
            dot.style.background = "#60a5fa";
        }
        return { success: true };
    }

    function _submitInput(value) {
        if (!value) return;
        clearInput();
        if (_stepEl) _stepEl.textContent = `Selected: ${value}`;
        if (typeof chrome !== "undefined" && chrome?.runtime?.sendMessage) {
            chrome.runtime.sendMessage({ action: "submit_user_input", value, task_id: _activeInputTaskId });
        }
    }

    return { show, hide, setPaused, updateStep, requestInput, clearInput, disableShield: _disableShield, enableShield: _enableShield };
})();



// ─────────────────────────────────────────────────────────────────────────────
// DOM Helpers
// ─────────────────────────────────────────────────────────────────────────────
function isVisible(el) {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return false;
    const style = window.getComputedStyle(el);
    return style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
}

function getCssSelector(el) {
    if (!el || el.nodeType !== Node.ELEMENT_NODE) return "";
    if (el.id && !/^[0-9]/.test(el.id) && !el.id.includes(" ")) return "#" + CSS.escape(el.id);
    const role = el.getAttribute("role");
    const ariaLabel = el.getAttribute("aria-label");
    const dataTooltip = el.getAttribute("data-tooltip");
    const tag = el.tagName.toLowerCase();
    
    if (role && ariaLabel) {
        return `${tag}[role="${CSS.escape(role)}"][aria-label*="${CSS.escape(ariaLabel)}" i]`;
    }
    if (role && dataTooltip) {
        return `${tag}[role="${CSS.escape(role)}"][data-tooltip*="${CSS.escape(dataTooltip)}" i]`;
    }
    if (el.name && ["input", "select", "textarea", "button"].includes(tag)) {
        return tag + `[name="${CSS.escape(el.name)}"]`;
    }
    if (ariaLabel) {
        return tag + `[aria-label="${CSS.escape(ariaLabel)}"]`;
    }
    if (dataTooltip) {
        return tag + `[data-tooltip="${CSS.escape(dataTooltip)}"]`;
    }
    return tag;
}

function inspectDOM(payload = {}) {
    const maxElements = payload.max_elements || 80;
    const interactiveTags = ["a", "button", "input", "select", "textarea", "summary"];
    const interactiveRoles = [
        "button", "link", "textbox", "checkbox", "radio", "combobox", "menuitem", 
        "tab", "listitem", "row", "gridcell", "option", "treeitem"
    ];

    // Universal check for open dialogs, obstructive modals, and popups on ANY site
    const dialog = document.querySelector(
        '[role="dialog"], [aria-modal="true"], dialog[open], .modal.show, .modal.open, [class*="popup" i], [class*="dialog" i], [class*="modal" i], [class*="gemini" i], .quantumWizDialogPaperdialog'
    );
    let activeModal = null;
    if (dialog && isVisible(dialog) && dialog.id !== "nexus-widget" && !dialog.closest("#__nexus-overlay-root__")) {
        const heading = dialog.querySelector('h1, h2, h3, [role="heading"]');
        const titleText = (heading ? heading.innerText : (dialog.getAttribute('aria-label') || dialog.innerText || "Modal")).trim().substring(0, 80).replace(/\s+/g, " ");
        
        // IMPORTANT: NEVER classify application workspaces (e.g. Gmail Compose, email drafts, message editors) as obstructive ad popups!
        const isAppComposerOrEditor = /compose|new message|draft|reply|forward|message|editor/i.test(titleText) ||
            dialog.querySelector('input[name="subjectbox"], [aria-label*="To" i], [aria-label*="Message Body" i], div[role="textbox"]');

        if (!isAppComposerOrEditor) {
            const closeBtn = dialog.querySelector(
                '[data-tooltip="Close"], [data-tooltip*="close" i], div[role="button"][data-tooltip*="close" i], [aria-label*="close" i], [aria-label*="dismiss" i], [role="button"][aria-label*="close" i], [role="button"][aria-label*="dismiss" i], button.close, [data-dismiss], button[aria-label="Close"], button[title*="close" i], [class*="close" i]'
            ) || document.querySelector('div[role="button"][data-tooltip="Close"], div[role="button"][data-tooltip*="close" i], div[role="button"][aria-label="Close" i], [aria-label="Close" i]');
            const effectiveCloseBtn = closeBtn ? (closeBtn.closest('button, [role="button"]') || closeBtn) : null;
            
            activeModal = {
                title: titleText,
                close_selector: effectiveCloseBtn ? getCssSelector(effectiveCloseBtn) : (closeBtn ? getCssSelector(closeBtn) : null),
                close_aria: effectiveCloseBtn ? (effectiveCloseBtn.getAttribute("aria-label") || effectiveCloseBtn.getAttribute("data-tooltip") || "Close") : "Close",
                is_intrusive: true
            };
        }
    }

    const all = Array.from(document.querySelectorAll("*"));
    const elements = [];

    for (const el of all) {
        if (elements.length >= maxElements) break;
        if (el.closest && el.closest("#__nexus-overlay-root__")) continue;

        const tag = el.tagName.toLowerCase();
        const role = el.getAttribute("role") || "";
        const isContentEditable = el.isContentEditable || el.getAttribute("contenteditable") === "true";
        const titleAttr = el.getAttribute("title") || "";
        const dataTestId = el.getAttribute("data-testid") || "";
        const isChatOrCell = /cell|list-item|chat|conversation/i.test(dataTestId);

        const isInteractive = interactiveTags.includes(tag) ||
            interactiveRoles.includes(role) ||
            isContentEditable ||
            el.hasAttribute("onclick") ||
            el.hasAttribute("data-tooltip") ||
            el.hasAttribute("tabindex") ||
            isChatOrCell ||
            (titleAttr && tag !== "html" && tag !== "head" && tag !== "body");

        if (isInteractive && isVisible(el)) {
            const rawText = (el.innerText || el.textContent || titleAttr || "").trim().replace(/\s+/g, " ");
            const tooltip = el.getAttribute("data-tooltip") || "";
            const ariaLabel = el.getAttribute("aria-label") || "";
            const isAiAssistant = /ask gemini|help me create|help me write|gemini|copilot|ai assistant/i.test(rawText + " " + ariaLabel + " " + tooltip);

            elements.push({
                tag: tag,
                role: role || (isContentEditable ? "textbox" : null),
                text: rawText ? rawText.substring(0, 80) : null,
                title: titleAttr || null,
                value: el.value ? String(el.value).substring(0, 50) : null,
                placeholder: el.getAttribute("placeholder") || null,
                aria_label: ariaLabel || tooltip || titleAttr || null,
                is_ai_assistant: isAiAssistant,
                selector: getCssSelector(el),
                id: el.id || null
            });
        }
    }

    return {
        url: window.location.href,
        title: document.title,
        active_modal: activeModal,
        interactive_elements: elements
    };
}

function queryDeep(selector, root = document) {
    if (!selector) return null;
    try {
        const el = root.querySelector(selector);
        if (el) return el;
    } catch (_) {}

    // Recurse into open shadow roots
    try {
        const all = root.querySelectorAll("*");
        for (const node of all) {
            if (node.shadowRoot) {
                const inner = queryDeep(selector, node.shadowRoot);
                if (inner) return inner;
            }
        }
    } catch (_) {}
    return null;
}

function getActiveComposeContainer() {
    const dialogs = Array.from(document.querySelectorAll('div[role="dialog"], div.AD, div.M9, div[aria-label*="Compose" i]'));
    const visible = dialogs.filter(d => {
        try {
            const rect = d.getBoundingClientRect();
            return rect.width > 120 && rect.height > 80 && window.getComputedStyle(d).display !== 'none';
        } catch (_) {
            return false;
        }
    });
    return visible.pop() || null;
}

function findElementFast(selector, text, xpath) {
    let target = null;
    const composeContainer = getActiveComposeContainer();

    // 1. Selector match (with deep shadow root recursion)
    if (selector) {
        if (composeContainer && (/to|recipient|subject|body|message|send/i.test(selector))) {
            try { target = composeContainer.querySelector(selector); } catch (_) {}
        }
        if (!target) {
            try { target = document.querySelector(selector); } catch (_) {}
        }
        if (!target) {
            target = queryDeep(selector);
        }
        if (!target && selector.toLowerCase().includes("add question")) {
            target = document.querySelector('div[role="button"][aria-label*="Add question" i], div[data-tooltip*="Add question" i], [aria-label*="Add question" i]');
        }
        if (!target && selector.toLowerCase().includes("close")) {
            target = document.querySelector('div[role="button"][aria-label*="Close" i], button[aria-label*="Close" i], [data-tooltip*="Close" i], .quantumWizDialogPaperdialogClose');
        }
        // Email action triggers fallback
        if (!target && /compose/i.test(selector)) {
            target = document.querySelector('div[gh="cm"], div[role="button"][gh="cm"], [data-tooltip*="Compose" i], [aria-label*="Compose" i], div.T-I.T-I-KE.L3, button[aria-label*="Compose" i], .compose-button');
        }
        if (!target && (/\bto\b|recipient/i.test(selector || "") || /\bto\b|recipient/i.test(text || ""))) {
            const root = composeContainer || document;
            target = root.querySelector('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[role="combobox"][aria-label*="To" i] input, div[aria-label*="To" i] input, input[name="to"], div.afv input, div[name="to"] input, input[peoplekit-id]');
            if (!target && composeContainer) {
                target = document.querySelector('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[role="combobox"][aria-label*="To" i] input, div[aria-label*="To" i] input, input[name="to"], div.afv input, div[name="to"] input, input[peoplekit-id]');
            }
        }
        if (!target && /subject/i.test(selector || "")) {
            const root = composeContainer || document;
            target = root.querySelector('input[name="subjectbox"], input[aria-label*="Subject" i], input[placeholder*="Subject" i]');
            if (!target && composeContainer) {
                target = document.querySelector('input[name="subjectbox"], input[aria-label*="Subject" i], input[placeholder*="Subject" i]');
            }
        }
        if (!target && /body|message/i.test(selector || "")) {
            const root = composeContainer || document;
            target = root.querySelector('div[role="textbox"][aria-label*="Message Body" i], div[contenteditable="true"][aria-label*="Body" i], div[g_editable="true"], div[aria-label*="Message Body" i], div[role="textbox"], div[contenteditable="true"]');
            if (!target && composeContainer) {
                target = document.querySelector('div[role="textbox"][aria-label*="Message Body" i], div[contenteditable="true"][aria-label*="Body" i], div[g_editable="true"], div[aria-label*="Message Body" i]');
            }
        }
        if (!target && /send/i.test(selector)) {
            const root = composeContainer || document;
            target = root.querySelector('div[role="button"][data-tooltip*="Send" i], div[role="button"][aria-label*="Send" i], button[aria-label*="Send" i], div.T-I.J-J5-Ji.aoO.v7.T-I-atl.L3');
            if (!target && composeContainer) {
                target = document.querySelector('div[role="button"][data-tooltip*="Send" i], div[role="button"][aria-label*="Send" i], button[aria-label*="Send" i]');
            }
        }
        if (!target && /\bcc\b/i.test(selector)) {
            const root = composeContainer || document;
            target = root.querySelector('span[role="button"][aria-label*="Add Cc" i], span[data-tooltip*="Cc" i], [aria-label*="Cc" i]');
        }
        if (!target && /\bbcc\b/i.test(selector)) {
            const root = composeContainer || document;
            target = root.querySelector('span[role="button"][aria-label*="Add Bcc" i], span[data-tooltip*="Bcc" i], [aria-label*="Bcc" i]');
        }
    }

    // 2. XPath match
    if (!target && xpath) {
        try {
            const res = document.evaluate(xpath, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null);
            target = res.singleNodeValue;
        } catch (_) {}
    }

    // 3. Robust Text Search across ALL elements (chat lists, rows, titles, buttons, spans, links)
    if (!target && (text || selector)) {
        const queryText = (text || "").trim().toLowerCase();
        if (queryText) {
            const candidates = Array.from(document.querySelectorAll(
                'button, [role="button"], a, [role="link"], [role="listitem"], [role="row"], [role="gridcell"], [role="option"], [role="tab"], [role="menuitem"], [data-testid*="cell" i], [data-testid*="list-item" i], [data-testid*="chat" i], [data-testid*="conversation" i], span[title], div[title], [tabindex], h1, h2, h3, h4, span, div, p'
            ));

            // Priority A: Exact match on title or aria-label
            target = candidates.find(el => {
                const title = (el.getAttribute("title") || "").trim().toLowerCase();
                const aria = (el.getAttribute("aria-label") || "").trim().toLowerCase();
                return (title === queryText || aria === queryText) && isVisible(el);
            });

            // Priority B: Exact match on innerText (ignoring surrounding whitespace)
            if (!target) {
                target = candidates.find(el => {
                    const t = (el.innerText || el.textContent || "").trim().toLowerCase();
                    return t === queryText && isVisible(el);
                });
            }

            // Priority C: Element title or aria-label contains queryText
            if (!target) {
                target = candidates.find(el => {
                    const title = (el.getAttribute("title") || "").trim().toLowerCase();
                    const aria = (el.getAttribute("aria-label") || "").trim().toLowerCase();
                    return (title.includes(queryText) || aria.includes(queryText)) && isVisible(el);
                });
            }

            // Priority D: Text includes queryText (prefer leaf/smaller element to avoid giant containers)
            if (!target) {
                const matching = candidates.filter(el => {
                    const t = (el.innerText || el.textContent || "").trim().toLowerCase();
                    return t.includes(queryText) && isVisible(el);
                });
                if (matching.length > 0) {
                    matching.sort((a, b) => (a.innerText?.length || 9999) - (b.innerText?.length || 9999));
                    target = matching[0];
                }
            }
        }
    }

    // 4. Selector Bundle Fallbacks (ariaLabel, placeholder, name, testId, boundingRect)
    if (!target && selector_bundle) {
        if (selector_bundle.ariaLabel) {
            try { target = document.querySelector(selector_bundle.ariaLabel); } catch (_) {}
        }
        if (!target && selector_bundle.testId) {
            try { target = document.querySelector(`[data-testid="${selector_bundle.testId}" i], [data-cy="${selector_bundle.testId}" i]`); } catch (_) {}
        }
        if (!target && selector_bundle.placeholder) {
            try { target = document.querySelector(`[placeholder*="${selector_bundle.placeholder.replace(/"/g, '\\"')}" i]`); } catch (_) {}
        }
        if (!target && selector_bundle.name) {
            try { target = document.querySelector(selector_bundle.name); } catch (_) {}
        }
        if (!target && selector_bundle.boundingRect) {
            const b = selector_bundle.boundingRect;
            if (typeof b.x === "number" && typeof b.y === "number") {
                try {
                    const cx = b.x + (b.width ? b.width / 2 : 5);
                    const cy = b.y + (b.height ? b.height / 2 : 5);
                    target = document.elementFromPoint(cx, cy);
                } catch (_) {}
            }
        }
    }

    // 5. VLM Feature Fallbacks (semantic_label, visual_landmark, bounding_rect)
    if (!target && vlm_features) {
        const sLabel = (vlm_features.semantic_label || "").trim().toLowerCase();
        if (sLabel) {
            const candidates = Array.from(document.querySelectorAll(
                'button, [role="button"], input, textarea, [contenteditable="true"], [role="textbox"], a, [role="link"], [role="option"], [role="tab"], div[title], span[title], [tabindex]'
            ));
            target = candidates.find(el => {
                const aria = (el.getAttribute("aria-label") || "").trim().toLowerCase();
                const title = (el.getAttribute("title") || "").trim().toLowerCase();
                const ph = (el.getAttribute("placeholder") || "").trim().toLowerCase();
                const inner = (el.innerText || el.textContent || "").trim().toLowerCase();
                return (aria.includes(sLabel) || title.includes(sLabel) || ph.includes(sLabel) || inner.includes(sLabel)) && isVisible(el);
            });
        }
        if (!target && vlm_features.bounding_rect) {
            const r = vlm_features.bounding_rect;
            if (typeof r.x === "number" && typeof r.y === "number") {
                try {
                    const cx = r.x + (r.width ? r.width / 2 : 5);
                    const cy = r.y + (r.height ? r.height / 2 : 5);
                    target = document.elementFromPoint(cx, cy);
                } catch (_) {}
            }
        }
    }

    return target;
}

async function waitForElement(selector, text, xpath, timeoutMs = 1500, vlm_features = null, selector_bundle = null) {
    const start = Date.now();
    let target = findElementFast(selector, text, xpath, vlm_features, selector_bundle);
    if (target) return target;

    // Fast dynamic polling (resolves immediately as soon as element renders/mounts)
    while (Date.now() - start < timeoutMs) {
        await new Promise(r => setTimeout(r, 60));
        target = findElementFast(selector, text, xpath, vlm_features, selector_bundle);
        if (target) return target;
    }
    return null;
}

// ─────────────────────────────────────────────────────────────────────────────
// ─────────────────────────────────────────────────────────────────────────────
// NEXUS High-Fidelity Virtual Mouse Cursor
// Emulates a real human mouse pointer with dynamic cursor shapes (pointer/text/default),
// realistic Bezier curve kinematics, tactile click ripples, and native CDP integration.
// ─────────────────────────────────────────────────────────────────────────────
const nexusVirtualCursor = (() => {
    let cursorHost = null;
    let cursorEl = null;
    let rippleEl = null;
    let currentX = Math.round(window.innerWidth / 2);
    let currentY = Math.round(window.innerHeight / 2);
    let fadeTimeout = null;

    function init() {
        if (cursorHost && document.contains(cursorHost)) return;

        cursorHost = document.createElement("div");
        cursorHost.id = "nexus-virtual-cursor-host";
        cursorHost.style.cssText = "position:fixed;top:0;left:0;width:0;height:0;overflow:visible;pointer-events:none!important;z-index:2147483646;";

        const shadow = cursorHost.attachShadow({ mode: "open" });
        shadow.innerHTML = `
            <style>
                .cursor-container {
                    position: fixed;
                    top: 0;
                    left: 0;
                    transform: translate3d(${currentX}px, ${currentY}px, 0);
                    pointer-events: none !important;
                    transition: opacity 0.22s ease;
                    opacity: 0;
                    z-index: 2147483646;
                    will-change: transform, opacity;
                    transform-origin: 0 0;
                }
                .cursor-container.active {
                    opacity: 1;
                }
                .cursor-container.clicking .pointer-icon {
                    transform: scale(0.82) rotate(-3deg);
                    transition: transform 0.05s cubic-bezier(0.2, 0, 0, 1);
                }
                .pointer-icon {
                    width: 26px;
                    height: 26px;
                    transform-origin: 2px 2px;
                    transition: transform 0.12s ease;
                    filter: drop-shadow(0 3px 8px rgba(0, 0, 0, 0.65)) drop-shadow(0 0 6px rgba(56, 189, 248, 0.75));
                    display: none;
                }
                .cursor-container.state-default .icon-default { display: block; }
                .cursor-container.state-pointer .icon-pointer { display: block; }
                .cursor-container.state-text .icon-text { display: block; }

                .pointer-badge {
                    position: absolute;
                    top: 17px;
                    left: 15px;
                    background: linear-gradient(135deg, #0284c7, #2563eb);
                    color: #ffffff;
                    font-size: 7.5px;
                    font-weight: 800;
                    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
                    padding: 1px 4px;
                    border-radius: 4px;
                    border: 1px solid rgba(255, 255, 255, 0.4);
                    box-shadow: 0 2px 6px rgba(0, 0, 0, 0.5), 0 0 8px rgba(56, 189, 248, 0.5);
                    letter-spacing: 0.06em;
                    pointer-events: none;
                    user-select: none;
                }
                .click-ripple {
                    position: absolute;
                    top: 2px;
                    left: 2px;
                    width: 32px;
                    height: 32px;
                    border-radius: 50%;
                    border: 2px solid #38bdf8;
                    background: radial-gradient(circle, rgba(56, 189, 248, 0.4) 0%, rgba(56, 189, 248, 0.05) 70%, transparent 100%);
                    box-shadow: 0 0 12px rgba(56, 189, 248, 0.8);
                    transform: translate(-50%, -50%) scale(0.1);
                    opacity: 0;
                    pointer-events: none;
                }
                .click-ripple.animate {
                    animation: nexusRipple 0.42s cubic-bezier(0.1, 0.8, 0.2, 1) forwards;
                }
                @keyframes nexusRipple {
                    0% {
                        transform: translate(-50%, -50%) scale(0.1);
                        opacity: 1;
                    }
                    100% {
                        transform: translate(-50%, -50%) scale(2.4);
                        opacity: 0;
                    }
                }
            </style>
            <div class="cursor-container state-default" id="cursor">
                <div class="click-ripple" id="ripple"></div>
                <!-- Default Arrow Cursor -->
                <svg class="pointer-icon icon-default" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M4 2L18.5 11.5L12 13.5L15 20.5L12 21.8L9 15L4 19V2Z" fill="#090d16" stroke="#38bdf8" stroke-width="1.8" stroke-linejoin="round"/>
                    <path d="M5.5 4.5L15.5 11.5L11 12.8L13.5 18.8L12.2 19.3L9.8 14L5.5 16.8V4.5Z" fill="#e0f2fe"/>
                </svg>
                <!-- Hand Pointer Cursor for buttons, links, tabs -->
                <svg class="pointer-icon icon-pointer" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M8 12V4.5C8 3.67 8.67 3 9.5 3C10.33 3 11 3.67 11 4.5V11M11 7C11 6.17 11.67 5.5 12.5 5.5C13.33 5.5 14 6.17 14 7V11M14 8C14 7.17 14.67 6.5 15.5 6.5C16.33 6.5 17 7.17 17 8V12M17 10C17 9.17 17.67 8.5 18.5 8.5C19.33 8.5 20 9.17 20 10V15C20 18.87 16.87 22 13 22H11C7.69 22 5 19.31 5 16V13.5C5 12.67 5.67 12 6.5 12C7.33 12 8 12.67 8 13.5V12" fill="#090d16" stroke="#38bdf8" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
                    <path d="M9.5 4.5V11M12.5 7V11M15.5 8V12" stroke="#e0f2fe" stroke-width="1.2" stroke-linecap="round"/>
                </svg>
                <!-- Text I-Beam Cursor for inputs, textareas, contenteditable -->
                <svg class="pointer-icon icon-text" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <path d="M7 4H17M7 20H17M12 4V20" stroke="#38bdf8" stroke-width="2.2" stroke-linecap="round"/>
                    <path d="M12 5V19" stroke="#ffffff" stroke-width="1.2" stroke-linecap="round"/>
                </svg>
                <div class="pointer-badge">AI</div>
            </div>
        `;

        (document.body || document.documentElement).appendChild(cursorHost);
        cursorEl = shadow.getElementById("cursor");
        rippleEl = shadow.getElementById("ripple");
    }

    function updateCursorStyle(el) {
        if (!cursorEl || !el) return;
        const tag = el.tagName ? el.tagName.toLowerCase() : "";
        const role = el.getAttribute ? (el.getAttribute("role") || "").toLowerCase() : "";
        const isText = ["input", "textarea"].includes(tag) ||
            el.isContentEditable ||
            role === "textbox" ||
            el.getAttribute?.("contenteditable") === "true";

        if (isText) {
            cursorEl.classList.remove("state-default", "state-pointer");
            cursorEl.classList.add("state-text");
            return;
        }

        const isPointer = ["button", "a", "select", "option", "summary"].includes(tag) ||
            ["button", "link", "tab", "option", "menuitem", "checkbox", "radio", "switch"].includes(role) ||
            el.hasAttribute?.("onclick") ||
            el.hasAttribute?.("data-tooltip") ||
            window.getComputedStyle?.(el)?.cursor === "pointer";

        if (isPointer) {
            cursorEl.classList.remove("state-default", "state-text");
            cursorEl.classList.add("state-pointer");
            return;
        }

        cursorEl.classList.remove("state-pointer", "state-text");
        cursorEl.classList.add("state-default");
    }

    async function moveTo(targetX, targetY, durationMs = null) {
        init();
        if (fadeTimeout) clearTimeout(fadeTimeout);

        cursorEl.classList.add("active");

        const startX = currentX;
        const startY = currentY;
        const dx = targetX - startX;
        const dy = targetY - startY;
        const dist = Math.hypot(dx, dy);

        // Adaptive natural duration based on distance if not specified
        const finalDuration = durationMs || Math.min(260, Math.max(90, Math.round(dist * 0.32 + 65)));

        // Calculate a realistic curved arc (perpendicular deflection)
        const arcAmt = Math.min(30, Math.max(0, dist * 0.1));
        const perpX = dist > 0 ? (-dy / dist) * arcAmt * 0.5 : 0;
        const perpY = dist > 0 ? (dx / dist) * arcAmt * 0.5 : 0;
        const ctrlX = (startX + targetX) / 2 + perpX;
        const ctrlY = (startY + targetY) / 2 + perpY;

        const startTime = performance.now();

        return new Promise(resolve => {
            function step(now) {
                const elapsed = now - startTime;
                const p = Math.min(elapsed / finalDuration, 1);
                // Ease out cubic
                const ease = 1 - Math.pow(1 - p, 3);

                // Quadratic Bezier interpolation: (1-t)^2 * P0 + 2(1-t)t * Pctrl + t^2 * P1
                const inv = 1 - ease;
                const interX = Math.round(inv * inv * startX + 2 * inv * ease * ctrlX + ease * ease * targetX);
                const interY = Math.round(inv * inv * startY + 2 * inv * ease * ctrlY + ease * ease * targetY);

                cursorEl.style.transform = `translate3d(${interX}px, ${interY}px, 0)`;

                // Update element hover state & cursor shape
                try {
                    const elUnder = document.elementFromPoint(interX, interY);
                    if (elUnder) {
                        updateCursorStyle(elUnder);
                        elUnder.dispatchEvent(new PointerEvent("pointermove", {
                            clientX: interX,
                            clientY: interY,
                            bubbles: true,
                            cancelable: true,
                            composed: true
                        }));
                    }
                } catch (_) {}

                if (p < 1) {
                    requestAnimationFrame(step);
                } else {
                    currentX = targetX;
                    currentY = targetY;
                    cursorEl.style.transform = `translate3d(${targetX}px, ${targetY}px, 0)`;
                    try {
                        const finalEl = document.elementFromPoint(targetX, targetY);
                        if (finalEl) updateCursorStyle(finalEl);
                    } catch (_) {}
                    resolve();
                }
            }
            requestAnimationFrame(step);
        });
    }

    async function hover(durationMs = 80) {
        init();
        try {
            const elUnder = document.elementFromPoint(currentX, currentY);
            if (elUnder) {
                updateCursorStyle(elUnder);
                const eventInit = {
                    clientX: currentX,
                    clientY: currentY,
                    bubbles: true,
                    cancelable: true,
                    composed: true
                };
                elUnder.dispatchEvent(new PointerEvent("pointerover", eventInit));
                elUnder.dispatchEvent(new MouseEvent("mouseenter", eventInit));
                elUnder.dispatchEvent(new MouseEvent("mouseover", eventInit));
            }
            if (typeof chrome !== "undefined" && chrome?.runtime?.sendMessage) {
                chrome.runtime.sendMessage({ action: "dispatch_native_move", x: currentX, y: currentY }).catch(() => {});
            }
        } catch (_) {}
        await new Promise(r => setTimeout(r, durationMs));
    }

    async function click(targetElement = null) {
        init();
        const x = currentX;
        const y = currentY;

        // Visual click reaction (depression + luminous ripple)
        cursorEl.classList.add("clicking");
        rippleEl.classList.remove("animate");
        void rippleEl.offsetWidth; // Force reflow
        rippleEl.classList.add("animate");

        // 1. Send native CDP click to background worker for true trusted browser input!
        try {
            if (typeof chrome !== "undefined" && chrome?.runtime?.sendMessage) {
                chrome.runtime.sendMessage({ action: "dispatch_native_click", x, y }).catch(() => {});
            }
        } catch (_) {}

        // 2. Real hit-test: resolve the true topmost element under the cursor point (ignoring our overlay/cursor host)
        let hitTarget = null;
        try {
            const el = document.elementFromPoint(x, y);
            if (el && !el.closest?.("#__nexus-overlay-root__") && !el.closest?.("#nexus-virtual-cursor-host")) {
                hitTarget = el;
            }
        } catch (_) {}

        const finalTarget = hitTarget || targetElement;

        const eventInit = {
            bubbles: true,
            cancelable: true,
            composed: true,
            view: window,
            clientX: x,
            clientY: y,
            screenX: (window.screenX || 0) + x,
            screenY: (window.screenY || 0) + y,
            button: 0,
            buttons: 1,
            which: 1,
        };

        // Ensure element is focused and dispatches a single clean click sequence
        const primary = targetElement || finalTarget;
        if (primary) {
            if (typeof primary.focus === "function") {
                try { primary.focus(); } catch (_) {}
            }
            primary.dispatchEvent(new PointerEvent("pointerdown", eventInit));
            primary.dispatchEvent(new MouseEvent("mousedown", eventInit));
        }

        // Realistic physical click duration hold (45ms)
        await new Promise(r => setTimeout(r, 45));

        cursorEl.classList.remove("clicking");

        const upInit = { ...eventInit, buttons: 0 };
        // Single clean click event
        if (primary) {
            primary.dispatchEvent(new PointerEvent("pointerup", upInit));
            primary.dispatchEvent(new MouseEvent("mouseup", upInit));
            primary.dispatchEvent(new MouseEvent("click", upInit));
        }

        fadeTimeout = setTimeout(() => {
            if (cursorEl) cursorEl.classList.remove("active");
        }, 1800);

        return { hitTarget, x, y };
    }

    return {
        moveTo,
        hover,
        click,
        get currentPos() { return { x: currentX, y: currentY }; }
    };
})();

async function clickElement(payload) {
    const { selector, text, xpath, x: explicitX, y: explicitY, vlm_features, selector_bundle } = payload || {};

    // 0. Gmail Compose duplicate protection: if compose is already open, do not click compose again!
    const isComposeAction = (selector && /compose/i.test(selector)) || (text && /compose/i.test(text));
    if (isComposeAction) {
        const existingCompose = getActiveComposeContainer();
        if (existingCompose) {
            console.log("[NEXUS] Compose dialog is already open; focusing existing compose container.");
            const toInput = existingCompose.querySelector('input[aria-label*="To" i], div[role="combobox"] input, input[name="to"]') || existingCompose;
            if (typeof toInput.focus === "function") toInput.focus();
            return {
                success: true,
                tag: "dialog",
                text: "Compose already open",
                already_open: true,
                url: window.location.href,
                title: document.title
            };
        }
    }

    let target = null;
    let x = explicitX;
    let y = explicitY;

    if (selector || text || xpath || vlm_features || selector_bundle) {
        target = await waitForElement(selector, text, xpath, 1500, vlm_features, selector_bundle);
    }

    // Coordinate fallback: if target not found by selector/text, but coordinates provided or resolvable
    if (!target && typeof x === "number" && typeof y === "number") {
        try {
            target = document.elementFromPoint(x, y);
        } catch (_) {}
    }

    if (!target && (typeof x !== "number" || typeof y !== "number")) {
        throw new Error(`Element not found for click (selector='${selector}', text='${text}')`);
    }

    // Resolve interactive ancestor if target is an inner span/icon/svg or list row
    const interactiveAncestor = target?.closest(
        'button, [role="button"], a, [role="link"], [role="listitem"], [role="row"], [role="gridcell"], [role="option"], [role="tab"], [role="menuitem"], [data-testid*="cell" i], [data-testid*="chat" i], [data-testid*="conversation" i], [data-testid*="list-item" i], [tabindex]'
    );
    const primaryTarget = interactiveAncestor || target;

    // If attempting to close/dismiss, also dispatch Escape key
    const isDismiss = (selector && /close|dismiss/i.test(selector)) || (text && /close|dismiss|cancel/i.test(text));
    if (isDismiss) {
        window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));
    }

    if (primaryTarget) {
        try {
            const r = primaryTarget.getBoundingClientRect();
            if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth) {
                primaryTarget.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
            }
            if (typeof primaryTarget.focus === "function") primaryTarget.focus();
            if (target !== primaryTarget && typeof target.focus === "function") target.focus();
        } catch (_) {}

        const rect = primaryTarget.getBoundingClientRect();
        x = Math.round(rect.left + rect.width / 2);
        y = Math.round(rect.top + rect.height / 2);
    }

    // Clamp coordinates to visible viewport
    x = Math.max(5, Math.min(window.innerWidth - 5, x || Math.round(window.innerWidth / 2)));
    y = Math.max(5, Math.min(window.innerHeight - 5, y || Math.round(window.innerHeight / 2)));

    // ── Secondary Virtual Cursor: Move, Hover, and Click like a normal human user ──
    await nexusVirtualCursor.moveTo(x, y, 120);
    await nexusVirtualCursor.hover(80);
    const cursorResult = await nexusVirtualCursor.click(primaryTarget || target);

    const hitEl = cursorResult.hitTarget || primaryTarget || target;

    // If clicking compose, allow Gmail a brief moment to instantiate the compose dialog
    if (isComposeAction) {
        await new Promise(r => setTimeout(r, 350));
    }

    // If clicking send, actively verify if the email was actually sent
    const isSendAction = (selector && /send/i.test(selector)) || (text && /send/i.test(text));
    if (isSendAction) {
        let sendConfirmed = false;
        let confirmationText = "";
        const sendStart = Date.now();
        while (Date.now() - sendStart < 3000) {
            await new Promise(r => setTimeout(r, 150));
            // 1. Check for "Message sent" toast or notification in Gmail/webmail
            const toast = document.querySelector('div[role="alert"], span#link_undo, div.b8.UC, div.vh, [aria-live="polite"], [aria-live="assertive"]');
            if (toast) {
                const toastContent = (toast.innerText || toast.textContent || "").trim();
                if (/sent|sending|message sent/i.test(toastContent)) {
                    sendConfirmed = true;
                    confirmationText = toastContent;
                    break;
                }
            }
            // 2. Check if the active compose dialog closed (indicates message sent)
            const openDialog = getActiveComposeContainer();
            if (!openDialog) {
                sendConfirmed = true;
                confirmationText = "Message dispatched (compose window closed)";
                break;
            }
        }
        return {
            success: true,
            tag: (hitEl?.tagName || "button").toLowerCase(),
            text: "Send",
            sent_confirmed: sendConfirmed,
            confirmation_message: confirmationText || "Email dispatched",
            url: window.location.href,
            title: document.title
        };
    }

    return {
        success: true,
        tag: (hitEl?.tagName || "element").toLowerCase(),
        text: (hitEl?.innerText || hitEl?.textContent || primaryTarget?.innerText || target?.innerText || "").substring(0, 50).trim(),
        coords: { x, y },
        hit_tag: cursorResult.hitTarget ? cursorResult.hitTarget.tagName.toLowerCase() : null,
        url: window.location.href,
        title: document.title
    };
}

async function hoverElement(payload) {
    const { selector, text, xpath, x: explicitX, y: explicitY, duration = 200 } = payload || {};
    let target = null;
    let x = explicitX;
    let y = explicitY;

    if (selector || text || xpath) {
        target = await waitForElement(selector, text, xpath, 1500);
    }

    if (target) {
        try {
            target.scrollIntoView({ behavior: "instant", block: "center", inline: "center" });
        } catch (_) {}
        const rect = target.getBoundingClientRect();
        x = Math.round(rect.left + rect.width / 2);
        y = Math.round(rect.top + rect.height / 2);
    }

    if (typeof x !== "number" || typeof y !== "number") {
        throw new Error(`Target not found for hover (selector='${selector}', text='${text}')`);
    }

    x = Math.max(5, Math.min(window.innerWidth - 5, x));
    y = Math.max(5, Math.min(window.innerHeight - 5, y));

    await nexusVirtualCursor.moveTo(x, y, 120);
    await nexusVirtualCursor.hover(duration);

    return { success: true, coords: { x, y } };
}

async function secondaryCursorClick(payload) {
    return clickElement(payload);
}

async function typeText(payload) {
    const { selector, text, clear_first = true, press_enter = false, vlm_features, selector_bundle } = payload || {};
    let el = null;
    const composeBox = getActiveComposeContainer();

    if (selector || vlm_features || selector_bundle) {
        el = await waitForElement(selector, null, null, 2500, vlm_features, selector_bundle);
        // Fallbacks for common email & form inputs scoped to active compose box
        if (!el && (/\bto\b|recipient/i.test(selector || "") || /recipient/i.test(payload?.description || ""))) {
            const root = composeBox || document;
            el = root.querySelector('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[role="combobox"][aria-label*="To" i] input, div[aria-label*="To" i] input, input[name="to"], div.afv input, div[name="to"] input, input[peoplekit-id]');
            if (!el) {
                el = await waitForElement('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[role="combobox"][aria-label*="To" i] input, div[aria-label*="To" i] input, input[name="to"]', null, null, 2500);
            }
            if (!el && composeBox) {
                const recipientsBtn = composeBox.querySelector('div[aria-label*="To" i], span[aria-label*="To" i], [data-tooltip*="Recipients" i], td[aria-label*="To" i], span.aB.gQ.pB');
                if (recipientsBtn) {
                    recipientsBtn.click();
                    await new Promise(r => setTimeout(r, 200));
                    el = composeBox.querySelector('input[aria-label*="To recipients" i], input[aria-label*="To" i], div[role="combobox"][aria-label*="To" i] input, div[aria-label*="To" i] input, input[name="to"]');
                }
            }
        }
        if (!el && /cc/i.test(selector)) {
            const root = composeBox || document;
            el = root.querySelector('input[aria-label*="Cc recipients" i], input[aria-label*="Cc" i], div[aria-label*="Cc" i] input, input[name="cc"]');
            if (!el) el = await waitForElement('input[aria-label*="Cc recipients" i], input[aria-label*="Cc" i], div[aria-label*="Cc" i] input, input[name="cc"]', null, null, 1500);
        }
        if (!el && /bcc/i.test(selector)) {
            const root = composeBox || document;
            el = root.querySelector('input[aria-label*="Bcc recipients" i], input[aria-label*="Bcc" i], div[aria-label*="Bcc" i] input, input[name="bcc"]');
            if (!el) el = await waitForElement('input[aria-label*="Bcc recipients" i], input[aria-label*="Bcc" i], div[aria-label*="Bcc" i] input, input[name="bcc"]', null, null, 1500);
        }
        if (!el && /subject/i.test(selector)) {
            const root = composeBox || document;
            el = root.querySelector('input[name="subjectbox"], input[aria-label*="Subject" i], input[placeholder*="Subject" i]');
            if (!el) el = await waitForElement('input[name="subjectbox"], input[aria-label*="Subject" i], input[placeholder*="Subject" i]', null, null, 1500);
        }
        if (!el && /body|message/i.test(selector)) {
            const root = composeBox || document;
            el = root.querySelector('div[role="textbox"][aria-label*="Message Body" i], div[contenteditable="true"][aria-label*="Body" i], div[g_editable="true"], div[aria-label*="Message Body" i], div[role="textbox"], div[contenteditable="true"]');
            if (!el) el = await waitForElement('div[role="textbox"][aria-label*="Message Body" i], div[contenteditable="true"][aria-label*="Body" i], div[g_editable="true"], div[aria-label*="Message Body" i]', null, null, 1500);
        }
    }

    if (!el) {
        const active = document.activeElement;
        const isBodySearch = /body|message/i.test(selector || "");
        if (active && active !== document.body && !active.closest("#__nexus-overlay-root__")) {
            if (isBodySearch && (active.name === "subjectbox" || active.getAttribute("aria-label")?.includes("Subject"))) {
                const root = composeBox || document;
                el = root.querySelector('div[role="textbox"], div[contenteditable="true"]');
            } else {
                el = active;
            }
        }
    }

    if (!el || el === document.body) {
        throw new Error(`Element '${selector}' not found for typing.`);
    }

    // If target is a container (like a question box or chip wrapper), resolve to the inner editable field
    if (!["input", "textarea"].includes(el.tagName.toLowerCase()) && !el.isContentEditable && el.getAttribute("role") !== "textbox") {
        const editable = el.querySelector('input, textarea, [contenteditable="true"], [role="textbox"]');
        if (editable) el = editable;
    }

    try {
        const r = el.getBoundingClientRect();
        if (r.top < 0 || r.bottom > window.innerHeight || r.left < 0 || r.right > window.innerWidth) {
            el.scrollIntoView({ behavior: "instant", block: "center" });
        }
    } catch (_) {}

    // Move secondary virtual cursor to field, click to focus like a real user
    try {
        const rect = el.getBoundingClientRect();
        const focusX = Math.round(rect.left + Math.min(25, Math.max(10, rect.width / 2)));
        const focusY = Math.round(rect.top + rect.height / 2);
        if (focusX > 0 && focusY > 0 && focusX < window.innerWidth && focusY < window.innerHeight) {
            await nexusVirtualCursor.moveTo(focusX, focusY, 90);
            await nexusVirtualCursor.click(el);
        } else {
            el.click();
        }
    } catch (_) {
        el.click();
    }
    el.focus();

    const isContentEditable = el.isContentEditable || el.getAttribute("contenteditable") === "true" || el.getAttribute("role") === "textbox";

    if (isContentEditable && el.tagName.toLowerCase() !== "input" && el.tagName.toLowerCase() !== "textarea") {
        if (clear_first) {
            el.innerText = "";
            el.innerHTML = "";
            document.execCommand("selectAll", false, null);
            document.execCommand("delete", false, null);
        }
        // Dispatch beforeinput for modern rich-text editors (Lexical, Quill, Draft.js, ProseMirror)
        el.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
        document.execCommand("insertText", false, text);
        if (el.innerText.trim() !== text.trim() && !el.innerText.includes(text.trim())) {
            el.innerText = text;
        }
        el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
        el.dispatchEvent(new Event("change", { bubbles: true }));

        const isSearchField = /search|query|\bq\b|find/i.test(el.getAttribute("aria-label") || el.id || selector || "");
        if (press_enter || isSearchField) {
            document.execCommand("insertParagraph", false, null);
            el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent("keypress", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
            if (window.location.hostname.includes("youtube.com")) {
                const ytBtn = document.querySelector("#search-icon-legacy, button#search-icon-legacy, button[aria-label*='Search' i]");
                if (ytBtn) ytBtn.click();
            }
        }

        return { success: true, value: el.innerText || el.textContent };
    }

    // Standard input / textarea
    const proto = el.tagName.toLowerCase() === "textarea"
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
    const nativeSetter = Object.getOwnPropertyDescriptor(proto, "value")?.set;

    if (clear_first) {
        if (nativeSetter) nativeSetter.call(el, "");
        else el.value = "";
        el.dispatchEvent(new Event("input", { bubbles: true }));
    }

    if (nativeSetter) nativeSetter.call(el, text);
    else el.value = text;

    el.dispatchEvent(new InputEvent("beforeinput", { bubbles: true, cancelable: true, inputType: "insertText", data: text }));
    el.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: text }));
    el.dispatchEvent(new Event("change", { bubbles: true }));

    // Detect search fields, recipient chips, or explicit press_enter:
    const isRecipientField = /to|cc|bcc|recipient/i.test(el.getAttribute("aria-label") || el.name || el.id || selector || "");
    const isSearchField = /search|query|\bq\b|find/i.test(el.getAttribute("aria-label") || el.name || el.id || el.getAttribute("placeholder") || selector || "") || el.getAttribute("type") === "search" || el.getAttribute("role") === "searchbox";
    const shouldPressEnter = press_enter || isSearchField || (isRecipientField && text.includes("@"));

    if (shouldPressEnter) {
        el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keypress", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true }));

        if (isRecipientField) {
            // Also dispatch Tab to ensure chip commits cleanly in Gmail/Outlook
            el.dispatchEvent(new KeyboardEvent("keydown", { key: "Tab", code: "Tab", keyCode: 9, which: 9, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent("keyup", { key: "Tab", code: "Tab", keyCode: 9, which: 9, bubbles: true }));
        }

        // On YouTube, trigger the dedicated search button specifically
        if (window.location.hostname.includes("youtube.com")) {
            const ytBtn = document.querySelector("#search-icon-legacy, button#search-icon-legacy, button[aria-label*='Search' i], #search-form button");
            if (ytBtn) {
                ytBtn.click();
            }
        }

        // Submit form or trigger submit button
        if (el.form) {
            try {
                if (typeof el.form.requestSubmit === "function") {
                    el.form.requestSubmit();
                } else {
                    el.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
                }
            } catch (e) {
                el.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
            }
        } else {
            const formContainer = el.closest("form, [role='search'], ytd-searchbox, .search-box");
            if (formContainer) {
                const submitBtn = formContainer.querySelector("button[type='submit'], input[type='submit'], button[aria-label*='Search' i], button[title*='Search' i]");
                if (submitBtn) submitBtn.click();
            }
        }
    }

    return { success: true, value: el.value };
}

async function dismissPopups() {
    // 1. Dispatch Escape key ONLY if an actual visible modal or dialog is present
    const activeModal = document.querySelector('[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog[open], .quantumWizDialogPaperdialog, .modal.show');
    if (activeModal && isVisible(activeModal)) {
        window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", code: "Escape", keyCode: 27, which: 27, bubbles: true }));
    }

    // Explicit dialog / modal / cookie banner dismiss selectors (strictly scoped so tab close buttons are never touched)
    const selectors = [
        '[role="dialog"] button[aria-label*="close" i]',
        '[role="dialog"] button[aria-label*="dismiss" i]',
        '[role="dialog"] [data-tooltip*="close" i]',
        '[role="dialog"] button.close',
        '[role="dialog"] .modal-close',
        '[role="alertdialog"] button[aria-label*="close" i]',
        '[role="alertdialog"] button[aria-label*="dismiss" i]',
        '[aria-modal="true"] button[aria-label*="close" i]',
        '[aria-modal="true"] button[aria-label*="dismiss" i]',
        '[aria-modal="true"] [data-tooltip*="close" i]',
        '.quantumWizDialogPaperdialogClose',
        '.modal [data-dismiss="modal"]',
        '.modal button.close',
        '.modal .modal-close',
        '.popup [data-dismiss="modal"]',
        '.popup-close',
        // Cookie / GDPR consent banners
        '#onetrust-accept-btn-handler',
        '#cookie-accept',
        '.cookie-banner button',
        'button[id*="cookie" i]',
        'button[class*="cookie" i]',
        'button[id*="consent" i]',
        'button[class*="consent" i]'
    ];

    for (const s of selectors) {
        const rawEl = document.querySelector(s);
        if (rawEl && isVisible(rawEl)) {
            const btn = rawEl.closest('button, [role="button"], a') || rawEl;
            btn.scrollIntoView({ behavior: "instant", block: "center" });
            const rect = btn.getBoundingClientRect();
            const pointerOpts = { bubbles: true, cancelable: true, clientX: rect.left + rect.width / 2, clientY: rect.top + rect.height / 2, view: window };
            btn.dispatchEvent(new PointerEvent("pointerdown", pointerOpts));
            btn.dispatchEvent(new MouseEvent("mousedown", pointerOpts));
            btn.dispatchEvent(new PointerEvent("pointerup", pointerOpts));
            btn.dispatchEvent(new MouseEvent("mouseup", pointerOpts));
            btn.click();
            return { dismissed: true, target: s };
        }
    }

    const buttons = Array.from(document.querySelectorAll('button, [role="button"], a[role="button"]'));
    const generalBannerWords = ["accept all", "allow all", "i agree", "got it", "maybe later", "not now", "skip", "start now", "let's start"];
    for (const btn of buttons) {
        if (!isVisible(btn)) continue;
        const t = (btn.innerText || btn.textContent || "").trim().toLowerCase();
        // Cookie / onboarding banners
        if (generalBannerWords.includes(t)) {
            btn.click();
            return { dismissed: true, target: t };
        }
        // "close" / "dismiss" words: ONLY click if strictly inside a dialog, modal, popup, or banner! Never on main page / tab bar
        if (["close", "dismiss", "no thanks"].includes(t)) {
            const inModalOrBanner = btn.closest('[role="dialog"], [role="alertdialog"], [aria-modal="true"], dialog, .modal, .popup, [class*="banner" i], [class*="cookie" i], [id*="cookie" i], [class*="consent" i], .quantumWizDialogPaperdialog');
            if (inModalOrBanner) {
                btn.click();
                return { dismissed: true, target: t };
            }
        }
    }

    // Fallback: If any dialog or backdrop remains, forcibly hide it
    const dialogs = document.querySelectorAll('[role="dialog"], [aria-modal="true"], dialog[open], .quantumWizDialogPaperdialog');
    let forciblyClosed = false;
    dialogs.forEach(d => {
        if (d.id !== "nexus-widget" && !d.closest("#__nexus-overlay-root__") && isVisible(d)) {
            const isOverlay = d.matches('[aria-modal="true"], dialog[open], .quantumWizDialogPaperdialog') ||
                Boolean(document.querySelector('.quantumWizDialogPaperdialogBackdrop, [class*="backdrop" i]'));
            if (isOverlay) {
                d.style.setProperty("display", "none", "important");
                forciblyClosed = true;
            }
        }
    });
    const backdrops = document.querySelectorAll('.quantumWizDialogPaperdialogBackdrop, [class*="backdrop" i]');
    backdrops.forEach(b => {
        if (!b.closest("#__nexus-overlay-root__")) b.remove();
    });

    if (forciblyClosed) {
        return { dismissed: true, target: "Forcibly hidden modal" };
    }

    return { dismissed: false };
}

async function pressKey(payload) {
    const { key = "Enter" } = payload;
    const active = document.activeElement || document.body;
    active.dispatchEvent(new KeyboardEvent("keydown", { key, code: key, bubbles: true }));
    active.dispatchEvent(new KeyboardEvent("keyup", { key, code: key, bubbles: true }));
    return { success: true, key };
}

async function selectOption(payload) {
    const { selector, value, label } = payload;
    const select = document.querySelector(selector);
    if (!select || select.tagName.toLowerCase() !== "select") {
        throw new Error(`Select element '${selector}' not found.`);
    }

    let option = null;
    if (value) option = Array.from(select.options).find(o => o.value === value);
    if (!option && label) option = Array.from(select.options).find(o => o.text.trim().toLowerCase() === label.trim().toLowerCase());

    if (option) {
        select.value = option.value;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        return { success: true, selected: option.text };
    }
    throw new Error(`Option not found in select '${selector}'.`);
}

/**
 * Returns the full HTML source of the active page, optionally scoped to a CSS selector.
 * max_chars defaults to 80000 to avoid hitting message size limits.
 */
function getPageSource(payload = {}) {
    const { selector = null, max_chars = 80000, include_meta = true } = payload;

    let html = "";
    if (selector) {
        const el = document.querySelector(selector);
        if (!el) throw new Error(`Element '${selector}' not found for source extraction.`);
        html = el.outerHTML;
    } else {
        html = document.documentElement.outerHTML;
    }

    const truncated = html.length > max_chars;
    const output = truncated ? html.substring(0, max_chars) + "\n<!-- [NEXUS: source truncated] -->" : html;

    const meta = include_meta ? {
        url: window.location.href,
        title: document.title,
        char_count: html.length,
        truncated
    } : {};

    return { source: output, ...meta };
}

/**
 * Executes arbitrary JavaScript in the page context and returns the result.
 * This is the console injection mechanism — scripts run with full page privileges.
 * Return values must be JSON-serialisable.
 */
async function executeScript(payload = {}) {
    const { script = "" } = payload;
    if (!script.trim()) throw new Error("No script provided to execute.");

    // Capture console.log output during execution
    const logs = [];
    const _origLog = console.log.bind(console);
    const _origWarn = console.warn.bind(console);
    const _origError = console.error.bind(console);
    console.log = (...args) => { logs.push({ level: "log", msg: args.map(String).join(" ") }); _origLog(...args); };
    console.warn = (...args) => { logs.push({ level: "warn", msg: args.map(String).join(" ") }); _origWarn(...args); };
    console.error = (...args) => { logs.push({ level: "error", msg: args.map(String).join(" ") }); _origError(...args); };

    let result = undefined;
    let error = null;
    try {
        // Support async scripts wrapped in an async IIFE
        const isAsync = /\bawait\b/.test(script);
        if (isAsync) {
            result = await new Function(`return (async () => { ${script} })()`)();
        } else {
            result = new Function(script)();
        }
    } catch (e) {
        error = e.message || String(e);
    } finally {
        console.log = _origLog;
        console.warn = _origWarn;
        console.error = _origError;
    }

    // Serialize result safely
    let serialized = null;
    try {
        serialized = result === undefined ? null : JSON.parse(JSON.stringify(result));
    } catch (e) {
        serialized = String(result);
    }

    return {
        result: serialized,
        logs,
        error,
        url: window.location.href,
        title: document.title
    };
}

/**
 * Smooth-scrolls to a CSS selector or scroll position.
 */
async function scrollToElement(payload = {}) {
    const { selector = null, x = 0, y = 0, behavior = "smooth" } = payload;
    if (selector) {
        const el = document.querySelector(selector);
        if (!el) throw new Error(`Scroll target '${selector}' not found.`);
        el.scrollIntoView({ behavior, block: "center" });
        return { success: true, target: selector };
    }
    window.scrollTo({ left: x, top: y, behavior });
    return { success: true, x, y };
}

// ─────────────────────────────────────────────────────────────────────────────
// Robust Web Media Player & Music Playback Integration
// ─────────────────────────────────────────────────────────────────────────────

async function getMediaInfo() {
    const hostname = window.location.hostname.toLowerCase();
    const mediaEls = Array.from(document.querySelectorAll("video, audio"));
    const isPlaying = mediaEls.some(el => !el.paused && !el.ended && el.currentTime > 0);

    let title = "";
    let artist = "";
    let service = "web";

    if (hostname.includes("spotify.com")) {
        service = "spotify";
        const titleEl = document.querySelector('[data-testid="now-playing-widget"] [data-testid="context-item-info-title"], [data-testid="context-item-link"]');
        const artistEl = document.querySelector('[data-testid="now-playing-widget"] [data-testid="context-item-info-artist"]');
        if (titleEl) title = titleEl.innerText || titleEl.textContent || "";
        if (artistEl) artist = artistEl.innerText || artistEl.textContent || "";
    } else if (hostname.includes("youtube.com")) {
        service = hostname.includes("music.youtube.com") ? "youtube_music" : "youtube";
        if (service === "youtube_music") {
            const t = document.querySelector(".title.ytmusic-player-bar");
            const a = document.querySelector(".byline.ytmusic-player-bar");
            if (t) title = t.innerText || t.textContent || "";
            if (a) artist = a.innerText || a.textContent || "";
        } else {
            const t = document.querySelector("h1.ytd-watch-metadata yt-formatted-string, #title h1, .ytp-title-link");
            const a = document.querySelector("#channel-name, .ytd-channel-name a");
            if (t) title = t.innerText || t.textContent || "";
            if (a) artist = a.innerText || a.textContent || "";
        }
    } else if (hostname.includes("soundcloud.com")) {
        service = "soundcloud";
        const t = document.querySelector(".playbackSoundBadge__titleLink");
        const a = document.querySelector(".playbackSoundBadge__lightLink");
        if (t) title = t.innerText || "";
        if (a) artist = a.innerText || "";
    }

    if (!title && typeof navigator !== "undefined" && navigator.mediaSession?.metadata?.title) {
        title = navigator.mediaSession.metadata.title;
        artist = navigator.mediaSession.metadata.artist || "";
    }
    if (!title) {
        title = document.title;
    }

    return {
        is_playing: isPlaying,
        title: (title || "").trim(),
        artist: (artist || "").trim(),
        service: service,
        has_media_elements: mediaEls.length > 0,
        volume: mediaEls[0]?.volume ?? 1.0,
        muted: mediaEls[0]?.muted ?? false,
    };
}

async function controlMedia(payload = {}) {
    const act = (payload?.action || "toggle").toLowerCase().trim();
    const volDelta = payload?.volume_delta || 0.1;
    const hostname = window.location.hostname.toLowerCase();
    const isSpotify = hostname.includes("spotify.com");
    const isYouTube = hostname.includes("youtube.com");
    const isSoundCloud = hostname.includes("soundcloud.com");
    const isApple = hostname.includes("apple.com");

    const mediaEls = Array.from(document.querySelectorAll("video, audio"));
    const primaryMedia = mediaEls.find(el => !el.paused) || mediaEls[0] || null;

    let appliedAction = act;
    let targetPlayer = isSpotify ? "Spotify Web" : isYouTube ? "YouTube" : isSoundCloud ? "SoundCloud" : isApple ? "Apple Music" : "HTML5 Media";

    switch (act) {
        case "play":
        case "resume": {
            if (isSpotify) {
                const playBtn = document.querySelector('button[data-testid="control-button-playpause"], button[aria-label*="Play" i]');
                if (playBtn) {
                    const aria = (playBtn.getAttribute("aria-label") || "").toLowerCase();
                    if (aria.includes("play")) playBtn.click();
                } else if (primaryMedia && primaryMedia.paused) {
                    await primaryMedia.play().catch(() => {});
                }
            } else if (isYouTube) {
                const v = document.querySelector("video");
                if (v && v.paused) {
                    await v.play().catch(() => {});
                } else if (!v) {
                    const btn = document.querySelector(".ytp-play-button, #play-pause-button");
                    if (btn) btn.click();
                }
            } else {
                for (const m of mediaEls) {
                    if (m.paused) await m.play().catch(() => {});
                }
            }
            break;
        }

        case "pause":
        case "stop": {
            if (isSpotify) {
                const pauseBtn = document.querySelector('button[data-testid="control-button-playpause"], button[aria-label*="Pause" i]');
                if (pauseBtn) {
                    const aria = (pauseBtn.getAttribute("aria-label") || "").toLowerCase();
                    if (aria.includes("pause")) pauseBtn.click();
                } else if (primaryMedia && !primaryMedia.paused) {
                    primaryMedia.pause();
                }
            } else if (isYouTube) {
                const v = document.querySelector("video");
                if (v && !v.paused) {
                    v.pause();
                } else {
                    const btn = document.querySelector(".ytp-play-button, #play-pause-button");
                    if (btn) btn.click();
                }
            } else {
                for (const m of mediaEls) {
                    if (!m.paused) m.pause();
                }
            }
            break;
        }

        case "toggle":
        case "play_pause": {
            if (isSpotify) {
                const btn = document.querySelector('button[data-testid="control-button-playpause"], button[aria-label*="Play" i], button[aria-label*="Pause" i]');
                if (btn) {
                    btn.click();
                } else if (primaryMedia) {
                    if (primaryMedia.paused) primaryMedia.play().catch(() => {});
                    else primaryMedia.pause();
                }
            } else if (isYouTube) {
                const v = document.querySelector("video");
                if (v) {
                    if (v.paused) v.play().catch(() => {});
                    else v.pause();
                } else {
                    const btn = document.querySelector(".ytp-play-button, #play-pause-button");
                    if (btn) btn.click();
                }
            } else if (primaryMedia) {
                if (primaryMedia.paused) primaryMedia.play().catch(() => {});
                else primaryMedia.pause();
            }
            break;
        }

        case "next":
        case "next_track":
        case "skip": {
            if (isSpotify) {
                const nextBtn = document.querySelector('button[data-testid="control-button-skip-forward"], button[aria-label*="Next" i]');
                if (nextBtn) nextBtn.click();
            } else if (isYouTube) {
                const nextBtn = document.querySelector('.ytp-next-button, button.next-button, [aria-label*="Next" i]');
                if (nextBtn) nextBtn.click();
            } else if (isSoundCloud) {
                const nextBtn = document.querySelector('.playControls__next');
                if (nextBtn) nextBtn.click();
            }
            break;
        }

        case "previous":
        case "prev":
        case "prev_track": {
            if (isSpotify) {
                const prevBtn = document.querySelector('button[data-testid="control-button-skip-back"], button[aria-label*="Previous" i]');
                if (prevBtn) prevBtn.click();
            } else if (isYouTube) {
                const prevBtn = document.querySelector('.ytp-prev-button, button.previous-button, [aria-label*="Previous" i]');
                if (prevBtn) prevBtn.click();
                else if (primaryMedia) primaryMedia.currentTime = 0;
            } else if (isSoundCloud) {
                const prevBtn = document.querySelector('.playControls__prev');
                if (prevBtn) prevBtn.click();
            }
            break;
        }

        case "volume_up": {
            mediaEls.forEach(el => {
                el.volume = Math.min(1.0, el.volume + volDelta);
            });
            break;
        }

        case "volume_down": {
            mediaEls.forEach(el => {
                el.volume = Math.max(0.0, el.volume - volDelta);
            });
            break;
        }

        case "mute":
        case "unmute": {
            mediaEls.forEach(el => {
                el.muted = act === "mute" ? true : act === "unmute" ? false : !el.muted;
            });
            const muteBtn = document.querySelector('.ytp-mute-button, button[aria-label*="Mute" i], button[aria-label*="volume" i]');
            if (muteBtn && mediaEls.length === 0) muteBtn.click();
            break;
        }
    }

    const info = await getMediaInfo();
    return {
        success: true,
        action: appliedAction,
        player: targetPlayer,
        media_info: info,
    };
}

async function autoPlayTopResult(payload = {}) {
    const hostname = window.location.hostname.toLowerCase();
    
    // Allow up to 3 seconds for search results or page elements to load
    for (let i = 0; i < 15; i++) {
        if (hostname.includes("spotify.com")) {
            // Check top result card play button or first tracklist row
            const topCardPlay = document.querySelector('[data-testid="top-result-card"] button[data-testid="play-button"], [data-testid="top-result-card"] [aria-label*="Play" i]');
            if (topCardPlay) {
                topCardPlay.click();
                return { success: true, method: "top_card_play" };
            }
            const firstTrackRow = document.querySelector('[data-testid="tracklist-row"]');
            if (firstTrackRow) {
                const rowPlayBtn = firstTrackRow.querySelector('button[data-testid="play-button"], button[aria-label*="Play" i]');
                if (rowPlayBtn) {
                    rowPlayBtn.click();
                    return { success: true, method: "track_row_play" };
                }
                firstTrackRow.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true }));
                return { success: true, method: "track_row_dblclick" };
            }
        } else if (hostname.includes("music.youtube.com")) {
            const playBtn = document.querySelector('ytmusic-responsive-list-item-renderer .play-button, ytmusic-card-shelf-renderer .play-button');
            if (playBtn) {
                playBtn.click();
                return { success: true, method: "ytmusic_play_button" };
            }
        } else if (hostname.includes("youtube.com")) {
            const firstVideo = document.querySelector('ytd-video-renderer a#video-title, ytd-video-renderer a#thumbnail, ytd-rich-item-renderer a#video-title');
            if (firstVideo) {
                firstVideo.click();
                return { success: true, method: "youtube_first_video_click" };
            }
        }
        await new Promise(r => setTimeout(r, 200));
    }
    return { success: false, reason: "No top result found or already playing" };
}

    // ── Enforce Single-Tab Automation Overlay (Suppressed in favor of Desktop Floating Pill) ──
    function syncAutomationOverlay() {
        try {
            nexusOverlay.hide({ delay: 0 });
        } catch (_) {}
    }

    try {
        syncAutomationOverlay();
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) {
                syncAutomationOverlay();
            }
        });
    } catch (_) {}
})();
