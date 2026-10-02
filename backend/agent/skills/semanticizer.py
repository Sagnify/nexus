"""
Action Semanticizer for NEXUS Skill Learning.
Filters observation noise, eliminates jitter, coalesces continuous keystrokes into text-entry steps,
and elevates raw interaction events into semantic automation actions.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional
from backend.agent.skills.session import DemonstrationEvent

logger = logging.getLogger("nexus.skills.semanticizer")


class RawSemanticAction:
    def __init__(
        self,
        action_type: str,
        execution_engine: str,
        title: str,
        target_app: Optional[str] = None,
        url: Optional[str] = None,
        selector_bundle: Optional[dict[str, Any]] = None,
        value: Optional[str] = None,
        is_sensitive: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.step_id = f"step-{uuid.uuid4().hex[:6]}"
        self.action_type = action_type
        self.execution_engine = execution_engine
        self.title = title
        self.target_app = target_app
        self.url = url
        self.selector_bundle = selector_bundle
        self.value = value
        self.is_sensitive = is_sensitive
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "action_type": self.action_type,
            "execution_engine": self.execution_engine,
            "title": self.title,
            "target_app": self.target_app,
            "url": self.url,
            "selector_bundle": self.selector_bundle,
            "value": self.value,
            "is_sensitive": self.is_sensitive,
            "metadata": self.metadata,
        }


class ActionSemanticizer:
    def semanticize(self, events: List[DemonstrationEvent]) -> List[RawSemanticAction]:
        """Convert a stream of raw demonstration events into normalized semantic actions."""
        if not events:
            return []

        semantic_actions: List[RawSemanticAction] = []
        i = 0
        n = len(events)

        while i < n:
            ev = events[i]

            # 1. Navigation Event
            if ev.event_type == "navigate" and ev.value:
                nav_url = ev.value
                meta = ev.metadata or {}
                hostname = meta.get("hostname")
                if not hostname and nav_url.startswith("http"):
                    try:
                        from urllib.parse import urlparse
                        hostname = urlparse(nav_url).netloc
                    except Exception:
                        pass

                page_title = meta.get("title") or hostname or nav_url
                if meta.get("action") == "tab_activated":
                    step_title = f"Switch to {page_title}"
                else:
                    step_title = f"Navigate to {page_title}"

                # Deduplicate consecutive identical navigations without other intervening actions
                if semantic_actions and semantic_actions[-1].action_type == "browser_navigate" and semantic_actions[-1].url == nav_url:
                    if meta.get("title") and not semantic_actions[-1].metadata.get("title"):
                        semantic_actions[-1].metadata.update(meta)
                    i += 1
                    continue

                semantic_actions.append(
                    RawSemanticAction(
                        action_type="browser_navigate",
                        execution_engine="browser",
                        title=step_title,
                        url=nav_url,
                        value=nav_url,
                        metadata=meta,
                    )
                )
                i += 1
                continue

            # 2. Sequential typing/input events on same target -> Coalesce into single type_text action
            if ev.event_type in ("input", "change"):
                def _get_target_key(event):
                    if not event.selector_bundle:
                        return None
                    b = event.selector_bundle
                    return b.get("id") or b.get("name") or b.get("ariaLabel") or b.get("testId") or b.get("cssPath") or b.get("xpath")

                target_key = _get_target_key(ev)
                final_val = ev.value
                is_sens = ev.is_sensitive
                last_ev = ev

                # Advance through consecutive typing events on the same element
                j = i + 1
                while j < n and events[j].event_type in ("input", "change"):
                    next_ev = events[j]
                    next_key = _get_target_key(next_ev)
                    # If same target or both targets match, or neither has selector but they're adjacent
                    if (target_key and next_key == target_key) or (not target_key and not next_key):
                        final_val = next_ev.value
                        if next_ev.is_sensitive:
                            is_sens = True
                        last_ev = next_ev
                        j += 1
                    else:
                        break

                # Check if followed immediately by an Enter keydown
                press_enter = False
                if j < n and events[j].event_type == "keydown" and events[j].key == "Enter":
                    press_enter = True
                    j += 1

                sel_bundle = last_ev.selector_bundle or {}
                elem_name = (
                    sel_bundle.get("name")
                    or sel_bundle.get("ariaLabel")
                    or last_ev.metadata.get("targetText")
                    or "input field"
                )
                title = f"Type into {elem_name}"

                meta = last_ev.metadata.copy()
                if press_enter:
                    meta["press_enter"] = True

                semantic_actions.append(
                    RawSemanticAction(
                        action_type="browser_type",
                        execution_engine="browser",
                        title=title,
                        url=last_ev.url,
                        selector_bundle=last_ev.selector_bundle,
                        value=final_val,
                        is_sensitive=is_sens,
                        metadata=meta,
                    )
                )
                i = j
                continue

            # 3. Click Event
            if ev.event_type == "click":
                ev_bundle = ev.selector_bundle or {}
                # Filter duplicate clicks within 250ms on exact same element (double click noise)
                if i + 1 < n and events[i + 1].event_type == "click":
                    t1 = ev_bundle.get("cssPath")
                    next_bundle = events[i + 1].selector_bundle or {}
                    t2 = next_bundle.get("cssPath")
                    if t1 and t1 == t2 and abs(events[i + 1].timestamp - ev.timestamp) < 0.35:
                        i += 1  # Skip the rapid repeat

                elem_name = (
                    ev_bundle.get("textAnchor")
                    or ev_bundle.get("ariaLabel")
                    or ev_bundle.get("name")
                    or ev.metadata.get("tagName")
                    or "element"
                )
                title = f"Click {elem_name}"

                semantic_actions.append(
                    RawSemanticAction(
                        action_type="browser_click",
                        execution_engine="browser",
                        title=title,
                        url=ev.url,
                        selector_bundle=ev.selector_bundle,
                        metadata=ev.metadata,
                    )
                )
                i += 1
                continue

            # 4. Keydown Event (Standalone Enter, Tab, Hotkey)
            if ev.event_type == "keydown":
                if ev.key in ("Enter", "Tab", "Escape"):
                    semantic_actions.append(
                        RawSemanticAction(
                            action_type="browser_press",
                            execution_engine="browser",
                            title=f"Press {ev.key}",
                            url=ev.url,
                            selector_bundle=ev.selector_bundle,
                            value=ev.key,
                            metadata=ev.metadata,
                        )
                    )
                i += 1
                continue

            # 5. Desktop Window Focus Event
            if ev.event_type == "window_focus":
                title = f"Activate {ev.target_app or 'Window'}: {ev.value}"
                semantic_actions.append(
                    RawSemanticAction(
                        action_type="desktop_focus",
                        execution_engine="desktop",
                        title=title,
                        target_app=ev.target_app,
                        value=ev.value,
                        metadata=ev.metadata,
                    )
                )
                i += 1
                continue

            i += 1

        return semantic_actions

    def semanticize_events(self, events: List[DemonstrationEvent]) -> List[RawSemanticAction]:
        return self.semanticize(events)



semanticizer = ActionSemanticizer()

