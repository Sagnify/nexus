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
                "description": "Insert executive overview heading",
                "tool": "document_add_heading",
                "args": {"text": "Executive Summary", "level": 1},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Summary Content",
                "description": "Insert executive overview body narrative",
                "tool": "document_add_paragraph",
                "args": {
                    "text": "This report provides an executive summary and analysis regarding {{topic}}. It synthesizes core objectives, relevant context, and actionable findings for operational review."
                },
                "risk_level": "SAFE",
            },
            {
                "title": "Add Detailed Analysis",
                "description": "Insert detailed analysis heading",
                "tool": "document_add_heading",
                "args": {"text": "Detailed Analysis & Findings", "level": 2},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Analysis Narrative",
                "description": "Insert comprehensive narrative paragraph",
                "tool": "document_add_paragraph",
                "args": {
                    "text": "A structured evaluation was conducted on {{topic}} to assess key drivers, performance indicators, and structural requirements. The following findings outline essential milestones and tactical considerations."
                },
                "risk_level": "SAFE",
            },
            {
                "title": "Add Recommendations Section",
                "description": "Insert actionable recommendations heading",
                "tool": "document_add_heading",
                "args": {"text": "Key Recommendations", "level": 2},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Recommendation 1",
                "description": "Insert first tactical bullet point",
                "tool": "document_add_bullet",
                "args": {"text": "Establish defined milestone tracking and validation checkpoints for {{topic}}."},
                "risk_level": "SAFE",
            },
            {
                "title": "Add Recommendation 2",
                "description": "Insert second tactical bullet point",
                "tool": "document_add_bullet",
                "args": {"text": "Implement structured oversight and data-driven continuous improvement loops."},
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
                "args": {"path": "{{path}}", "min_paragraphs": 2},
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
                "title": "Populate Table Structure",
                "description": "Populate headers and structured rows",
                "tool": "spreadsheet_write_range",
                "args": {
                    "start_cell": "A1",
                    "sheet": "Data",
                    "values": [
                        ["ID", "Item / Description", "Category", "Status", "Target Period", "Metric Score"],
                        [101, "Milestone Assessment", "Operations", "Completed", "Q1", 95],
                        [102, "Workflow Implementation", "Engineering", "Active", "Q2", 120],
                        [103, "Quality Verification", "QA", "Scheduled", "Q2", 85],
                        [104, "Performance Review", "Management", "Pending", "Q3", 110],
                    ],
                },
                "risk_level": "SAFE",
            },
            {
                "title": "Format Header Row",
                "description": "Apply professional header styling and bold fill",
                "tool": "spreadsheet_format_range",
                "args": {"range": "A1:F1", "sheet": "Data", "bold": True, "fill_color": "1F4E78", "color": "FFFFFF"},
                "risk_level": "SAFE",
            },
            {
                "title": "Create Formatted Table",
                "description": "Convert range into Excel table",
                "tool": "spreadsheet_create_table",
                "args": {"range": "A1:F5", "name": "DataTable", "sheet": "Data"},
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
                "args": {"path": "{{path}}", "min_rows": 2},
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
    
    Substantive queries that require deep topic research, dynamic web scraping,
    custom real-world rankings, or bespoke tabular data are explicitly NOT intercepted here;
    they are allowed to flow directly to the LLM Planner / Deep Research Engine.
    """
    clean = query.strip()
    lower = clean.lower()

    # Substantive markers that require LLM planner / deep research / live data generation
    substantive_markers = (
        "research", "study", "analysis", "deep", "in-depth", "investigate",
        "history", "industrialization", "market", "economy", "citations", "sources",
        "overview of", "summary of", "findings", "top 10", "top 5", "top ",
        "best ", "chess", "players", "champions league", "scorers", "crypto",
        "budget", "expenses", "revenue", "sales", "financial", "quarterly",
        "formula", "chart", "graph", "compare", "comparison"
    )
    if any(m in lower for m in substantive_markers):
        return None, {}

    # Match Word Document boilerplate requests (e.g. "create a word document template", "make a blank docx report")
    word_match = re.search(
        r"(?:create|generate|write|make)\s+(?:(?:a|an)\s+)?(?:word\s+)?(?:document|doc|docx|report)(?:\s+(?:template|boilerplate|skeleton))?(?:\s+(?:on|about|for)\s+[\"']?([a-zA-Z0-9_\-\s]{2,25})[\"']?)?(?:\s+(?:named|called|at|to)\s+[\"']?([a-zA-Z0-9_\-\.\/]+)[\"']?)?$",
        lower,
    )
    if word_match and not any(w in lower for w in ("powerpoint", "presentation", "excel", "spreadsheet")):
        # Only use canonical template if the request is generic or explicitly asks for a template
        is_generic = not word_match.group(1) or any(w in lower for w in ("template", "boilerplate", "sample", "blank", "general"))
        if is_generic:
            topic = (word_match.group(1) or "General").strip()
            custom_path = word_match.group(2)
            safe_topic_slug = re.sub(r"[^\w\s-]", "", topic).strip().replace(" ", "_")[:30] or "report"
            path = custom_path or f"Desktop/{safe_topic_slug}.docx"
            if not path.endswith(".docx"):
                path += ".docx"
            return "create_word_report", {"topic": topic.capitalize(), "path": path}

    # Match Excel Spreadsheet boilerplate requests (e.g. "create an empty excel sheet", "create excel spreadsheet template")
    excel_match = re.search(
        r"(?:create|generate|make)\s+(?:(?:a|an)\s+)?(?:excel\s+)?(?:spreadsheet|sheet|workbook|excel|xlsx|csv)(?:\s+(?:file|sheet|spreadsheet|workbook))?(?:\s+(?:template|boilerplate|skeleton|sample))?(?:\s+(?:named|called|at|to)\s+[\"']?([a-zA-Z0-9_\-\.\/]+)[\"']?)?$",
        lower,
    )
    if excel_match and any(w in lower for w in ("excel", "spreadsheet", "xlsx")):
        # Only use canonical template if the request is generic/template
        custom_path = excel_match.group(1)
        path = custom_path or "Desktop/data_template.xlsx"
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
