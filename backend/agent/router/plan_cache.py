"""
NEXUS Normalized Plan Cache
===========================
Caches verified, multi-step structured execution plans by normalized intent signature.
Re-uses workflow skeletons for structurally identical requests with dynamic argument
substitution (e.g. topic, filename, recipient), saving 100% of LLM reasoning & planning tokens.
"""
from __future__ import annotations

import re
import time
import copy
import uuid
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("nexus.plan_cache")


@dataclass
class CachedPlanTemplate:
    signature: str
    template_plan: list[dict[str, Any]]
    param_keys: list[str]
    success_count: int = 1
    last_used: float = field(default_factory=time.time)


# Pre-warmed canonical plan templates for common multi-step tasks
CANONICAL_TEMPLATES: dict[str, CachedPlanTemplate] = {
    # 1. Word Document Report Creation
    "create_word_report": CachedPlanTemplate(
        signature="create_word_report",
        template_plan=[
            {
                "title": "Create Document",
                "description": "Initialize Word document workspace",
                "tool": "document_create",
                "args": {},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Title",
                "description": "Insert document title for {{topic}}",
                "tool": "document_add_title",
                "args": {"text": "Report: {{topic}}"},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Executive Summary",
                "description": "Insert executive overview heading and analysis",
                "tool": "document_add_heading",
                "args": {"text": "Executive Summary", "level": 1},
                "risk_level": "SAFE",
            },
            {
                "title": "Save Document to Disk",
                "description": "Save generated Word document to {{path}}",
                "tool": "document_save",
                "args": {"path": "{{path}}"},
                "risk_level": "SAFE",
            },
            {
                "title": "Verify Document Integrity",
                "description": "Verify file existence and structure on disk",
                "tool": "document_verify",
                "args": {"path": "{{path}}"},
                "risk_level": "READ_ONLY",
            },
        ],
        param_keys=["topic", "path"],
    ),

    # 2. Excel Spreadsheet Creation
    "create_excel_sheet": CachedPlanTemplate(
        signature="create_excel_sheet",
        template_plan=[
            {
                "title": "Create Spreadsheet",
                "description": "Initialize Excel spreadsheet",
                "tool": "spreadsheet_create",
                "args": {"sheet_name": "Data"},
                "risk_level": "SAFE",
            },
            {
                "title": "Save Workbook to Disk",
                "description": "Save generated Excel file to {{path}}",
                "tool": "spreadsheet_save",
                "args": {"path": "{{path}}"},
                "risk_level": "SAFE",
            },
            {
                "title": "Verify Workbook Integrity",
                "description": "Verify file existence and cell data",
                "tool": "spreadsheet_verify",
                "args": {"path": "{{path}}"},
                "risk_level": "READ_ONLY",
            },
        ],
        param_keys=["path"],
    ),
}

_DYNAMIC_CACHE: dict[str, CachedPlanTemplate] = {}
_MAX_DYNAMIC_ENTRIES = 500


def extract_template_signature(query: str) -> tuple[Optional[str], dict[str, str]]:
    """
    Analyzes user query to extract a normalized template signature and parameter mappings.
    Returns (signature, params).
    """
    clean = query.strip()
    lower = clean.lower()

    # Match Word Document Report queries
    word_match = re.search(
        r"(?:create|generate|write|make)\s+(?:(?:a|an)\s+)?(?:word\s+)?(?:document|doc|docx|report)\s+(?:on|about|for)\s+[\"']?(.+?)[\"']?(?:\s+(?:named|called|at|to)\s+[\"']?([a-zA-Z0-9_\-\.\/]+)[\"']?)?$",
        lower,
    )
    if word_match and not any(w in lower for w in ("powerpoint", "presentation", "excel", "spreadsheet")):
        topic = word_match.group(1).strip()
        custom_path = word_match.group(2)
        safe_topic_slug = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:30] or "report"
        path = custom_path or f"Desktop/{safe_topic_slug}.docx"
        if not path.endswith(".docx"):
            path += ".docx"
        return "create_word_report", {"topic": topic.capitalize(), "path": path}

    # Match Excel Spreadsheet queries
    excel_match = re.search(
        r"(?:create|generate|make)\s+(?:(?:a|an)\s+)?(?:excel\s+)?(?:spreadsheet|sheet|workbook|excel|xlsx|csv)(?:\s+(?:file|sheet|spreadsheet|workbook))?(?:\s+(?:on|about|for)\s+[\"']?(.+?)[\"']?)?(?:\s+(?:named|called|at|to)\s+[\"']?([a-zA-Z0-9_\-\.\/]+)[\"']?)?$",
        lower,
    )
    if excel_match and any(w in lower for w in ("excel", "spreadsheet", "xlsx")):
        topic = excel_match.group(1) or "Data"
        custom_path = excel_match.group(2)
        safe_slug = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:30] or "data"
        path = custom_path or f"Desktop/{safe_slug}.xlsx"
        if not path.endswith(".xlsx"):
            path += ".xlsx"
        return "create_excel_sheet", {"path": path}

    return None, {}


def get_cached_plan(query: str) -> Optional[list[dict[str, Any]]]:
    """
    Checks cache for an applicable plan template.
    If matched, instantiates the template with query parameters.
    """
    signature, params = extract_template_signature(query)
    if not signature:
        return None

    template = CANONICAL_TEMPLATES.get(signature) or _DYNAMIC_CACHE.get(signature)
    if not template:
        return None

    # Instantiate plan with new UUIDs and parameter replacements
    instantiated_plan: list[dict[str, Any]] = []
    for step in template.template_plan:
        step_copy = copy.deepcopy(step)
        step_copy["id"] = f"step_{uuid.uuid4().hex[:6]}"
        step_copy["status"] = "pending"

        # Parameterize strings in title, description, and args
        for k, v in params.items():
            token = f"{{{{{k}}}}}"
            if token in step_copy.get("title", ""):
                step_copy["title"] = step_copy["title"].replace(token, v)
            if token in step_copy.get("description", ""):
                step_copy["description"] = step_copy["description"].replace(token, v)
            for arg_key, arg_val in list(step_copy.get("args", {}).items()):
                if isinstance(arg_val, str) and token in arg_val:
                    step_copy["args"][arg_key] = arg_val.replace(token, v)

        instantiated_plan.append(step_copy)

    template.success_count += 1
    template.last_used = time.time()
    logger.info("[PlanCache] Hit for signature '%s' with params %s", signature, params)
    return instantiated_plan


def store_successful_plan(query: str, plan: list[dict[str, Any]]) -> None:
    """Stores a successful plan into the dynamic LRU cache for future acceleration."""
    if not plan or len(plan) < 2:
        return

    signature, _ = extract_template_signature(query)
    if not signature:
        # Generate a structural signature based on tool sequence
        tool_seq = "_".join(s.get("tool", "") for s in plan if s.get("tool"))
        if not tool_seq:
            return
        signature = f"seq_{tool_seq}"

    if len(_DYNAMIC_CACHE) >= _MAX_DYNAMIC_ENTRIES:
        oldest_key = min(_DYNAMIC_CACHE.keys(), key=lambda k: _DYNAMIC_CACHE[k].last_used)
        del _DYNAMIC_CACHE[oldest_key]

    clean_plan = copy.deepcopy(plan)
    for s in clean_plan:
        s["status"] = "pending"
        s.pop("result", None)
        s.pop("error", None)

    _DYNAMIC_CACHE[signature] = CachedPlanTemplate(
        signature=signature,
        template_plan=clean_plan,
        param_keys=[],
        last_used=time.time(),
    )
