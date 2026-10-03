"""
VLM Feature Extractor for NEXUS Demonstration Learning.
Extracts semantic visual context, UI role, icons/landmarks, and spatial features
from interaction snapshots captured during skill demonstration without requiring full screen recordings.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from backend.agent.skills.session import DemonstrationEvent

logger = logging.getLogger("nexus.skills.vlm_extractor")


class VLMInteractionFeatureExtractor:
    """Extracts UI features from demonstration snapshots and interaction coordinates."""

    @staticmethod
    def _heuristic_features(
        event_type: str,
        selector_bundle: Optional[dict] = None,
        value: Optional[str] = None,
        target_text: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Fast fallback when snapshot is unavailable or VLM is busy."""
        bundle = selector_bundle or {}
        meta = metadata or {}
        tag = (meta.get("tagName") or bundle.get("role") or "").lower()
        aria = (bundle.get("ariaLabel") or bundle.get("title") or meta.get("title") or "").strip()
        anchor = (target_text or bundle.get("textAnchor") or "").strip()
        if aria and (not anchor or len(anchor) <= 2 or anchor in ("+", "-", "x", "×", "…", "•••", "v", "^")):
            text = aria
        else:
            text = anchor or aria
        rect = bundle.get("boundingRect") or {}

        # Infer role
        if tag in ("button", "a") or bundle.get("role") in ("button", "link"):
            role = "button"
        elif tag in ("input", "textarea") or bundle.get("role") in ("textbox", "searchbox"):
            role = "input_field"
        elif tag == "select" or bundle.get("role") in ("combobox", "listbox", "option"):
            role = "dropdown"
        elif event_type == "navigate":
            role = "navigation"
        else:
            role = tag or event_type

        # Infer landmark
        landmark = ""
        text_lower = text.lower()
        if any(w in text_lower for w in ("+", "add", "new", "create")):
            landmark = "Add / Create Icon"
        elif any(w in text_lower for w in ("delete", "trash", "remove")):
            landmark = "Delete / Trash Icon"
        elif any(w in text_lower for w in ("search", "find")):
            landmark = "Search Icon"
        elif any(w in text_lower for w in ("save", "submit", "send")):
            landmark = "Submit / Action Button"

        return {
            "visual_role": role,
            "semantic_label": text or f"{role.replace('_', ' ').title()}",
            "visual_landmark": landmark,
            "visual_context": f"Element {tag or role} at {rect.get('x', 0)},{rect.get('y', 0)}" if rect else f"Element {tag or role}",
            "bounding_rect": rect,
            "expected_effect": f"Dispatches {event_type} interaction",
        }

    async def extract_features_for_event(
        self,
        event: DemonstrationEvent,
        prompt_intent: Optional[str] = None,
        timeout_seconds: float = 4.0,
    ) -> dict[str, Any]:
        """Extract visual and semantic features for a single interaction event using VLM."""
        bundle = event.selector_bundle or {}
        meta = event.metadata or {}
        rect = bundle.get("boundingRect") or {}
        target_text = meta.get("targetText") or bundle.get("textAnchor") or ""
        coords = meta.get("clickCoords") or ({"x": rect.get("x"), "y": rect.get("y")} if rect else None)

        # If no snapshot, return deterministic heuristics instantly (0ms)
        if not event.snapshot or not event.snapshot.startswith("data:image"):
            return self._heuristic_features(
                event.event_type,
                selector_bundle=bundle,
                value=event.value,
                target_text=target_text,
                metadata=meta,
            )

        prompt = (
            f"You are NEXUS UI Vision Analyzer. A user demonstrated an action for '{prompt_intent or 'Workflow'}':\n"
            f"- Action: {event.event_type}\n"
            f"- Element Text/Selector: {target_text or bundle.get('cssPath') or bundle.get('xpath')}\n"
            f"- Coordinates/BoundingBox: {json.dumps(coords or {})}\n\n"
            "Analyze the attached interaction snapshot and extract concise, reusable UI features:\n"
            "1. visual_role: semantic element type (e.g. 'button', 'input_field', 'dropdown', 'tab', 'toolbar_item')\n"
            "2. semantic_label: clear human label (e.g. 'Add question', 'Form title', 'Short answer option')\n"
            "3. visual_landmark: distinctive icon/color/shape (e.g. 'plus icon in circle', 'blue button', 'chevron')\n"
            "4. visual_context: spatial position / parent card (e.g. 'floating question toolbar on right', 'top header card')\n"
            "5. expected_effect: expected state transition (e.g. 'creates new question card', 'types title')\n\n"
            "Reply ONLY with JSON:\n"
            "{\"visual_role\": \"...\", \"semantic_label\": \"...\", \"visual_landmark\": \"...\", \"visual_context\": \"...\", \"expected_effect\": \"...\"}"
        )

        try:
            from backend.agent.router.model_router import call_vision_with_dynamic_switch
            res = await asyncio.wait_for(
                call_vision_with_dynamic_switch(prompt=prompt, data_url=event.snapshot, max_tokens=220),
                timeout=timeout_seconds,
            )
            match = re.search(r"\{[\s\S]*\}", res)
            if match:
                parsed = json.loads(match.group(0))
                parsed["bounding_rect"] = rect
                return parsed
        except Exception as e:
            logger.debug("[VLMFeatureExtractor] Vision extraction skipped (%s), using heuristics", e)

        return self._heuristic_features(
            event.event_type,
            selector_bundle=bundle,
            value=event.value,
            target_text=target_text,
            metadata=meta,
        )

    async def enrich_events(
        self,
        events: List[DemonstrationEvent],
        prompt_intent: Optional[str] = None,
        max_vlm_events: int = 8,
    ) -> List[DemonstrationEvent]:
        """
        Enrich demonstration events with VLM features concurrently.
        Processes up to max_vlm_events key interactions to preserve high speed (<3.5s).
        """
        if not events:
            return events

        # Identify candidate events for VLM analysis (interactive clicks, inputs, changes)
        interactive_events = [
            ev for ev in events
            if ev.event_type in ("click", "input", "change", "keydown") and ev.snapshot
        ]

        # Prioritize key events (evenly sampled if many)
        if len(interactive_events) > max_vlm_events:
            step = len(interactive_events) / max_vlm_events
            candidate_events = [interactive_events[int(i * step)] for i in range(max_vlm_events)]
        else:
            candidate_events = interactive_events

        candidate_ids = {ev.event_id for ev in candidate_events}

        async def _enrich_single(ev: DemonstrationEvent):
            if ev.event_id in candidate_ids and ev.snapshot:
                feat = await self.extract_features_for_event(ev, prompt_intent, timeout_seconds=3.0)
            else:
                meta = ev.metadata or {}
                bundle = ev.selector_bundle or {}
                feat = self._heuristic_features(
                    ev.event_type,
                    selector_bundle=bundle,
                    value=ev.value,
                    target_text=meta.get("targetText"),
                    metadata=meta,
                )
            new_meta = dict(ev.metadata or {})
            new_meta["vlm_features"] = feat
            ev.metadata = new_meta

        await asyncio.gather(*[_enrich_single(ev) for ev in events], return_exceptions=False)
        logger.info(
            "[VLMFeatureExtractor] Enriched %d demonstration events with visual/semantic feature metadata",
            len(events),
        )
        return events


vlm_extractor = VLMInteractionFeatureExtractor()
