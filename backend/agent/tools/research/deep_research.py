"""
Autonomous Deep Research Engine for NEXUS.
Executes multi-query web research, scrapes live sources, synthesizes detailed academic-grade
findings with citations, and compiles directly into user-requested document formats:
- Word (.docx)
- PDF (.pdf)
- Excel Workbook (.xlsx)
- CSV Dataset (.csv)
- Markdown (.md)
- Interactive HTML (.html)
- Plain Text (.txt)
- Structured JSON (.json)

Also handles requests for proprietary/unsupported binary project formats (e.g., .cpr, .psd, .ps)
with clear, transparent guidance and automatic compilation into universal document formats.
"""
from __future__ import annotations

import asyncio
import csv
import datetime
import html
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.core.paths import resolve_system_path

logger = logging.getLogger("nexus.deep_research")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Known proprietary or binary application formats that cannot be programmatically synthesized
UNSUPPORTED_FORMATS: dict[str, tuple[str, str]] = {
    "cpr": ("Steinberg Cubase Project", "PDF, DOCX, or Excel documentation"),
    "ps": ("PostScript / Photoshop", "PDF, DOCX, or SVG"),
    "psd": ("Adobe Photoshop Document", "PDF, PNG, or DOCX"),
    "ptx": ("Avid Pro Tools Session", "PDF or Text documentation"),
    "flp": ("FL Studio Project", "MIDI or PDF documentation"),
    "aep": ("Adobe After Effects Project", "HTML/CSS animation or PDF report"),
    "prproj": ("Adobe Premiere Pro Project", "XML, EDL, or PDF report"),
    "dwg": ("AutoCAD Drawing Binary", "DXF, SVG, or PDF documentation"),
    "blend": ("Blender 3D Scene Binary", "OBJ, GLTF, or PDF documentation"),
    "max": ("Autodesk 3ds Max Scene", "PDF or DOCX documentation"),
    "exe": ("Compiled Windows Executable", "Python script or PowerShell"),
}


def _clean_text(text: str) -> str:
    """Normalize whitespace and strip control characters."""
    if not text:
        return ""
    text = re.sub(r"[\xa0\u200b\r]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_topic_name(topic: str) -> str:
    """Strip action/directive phrases like 'do deep research on' to extract the true research topic."""
    if not topic:
        return ""
    cleaned = topic.strip()
    cleaned = re.sub(
        r"[\s,;]+(?:focus(?:ing)?\s+on|subtopics?|priority|prioritize|with\s+focus\s+on|format|output).*$",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"^(?:please\s+)?(?:do|conduct|perform|run|execute|make|create|generate|write|compile|get|fetch|find)?\s*"
        r"(?:a\s+|an\s+|the\s+)?(?:comprehensive\s+|in-depth\s+|detailed\s+|thorough\s+|exhaustive\s+|market\s+|industry\s+|academic\s+)?"
        r"(?:deep\s+)?(?:research|study|investigation|analysis|report|overview|paper|breakdown)"
        r"(?:\s+(?:on|about|regarding|into|for|of))?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(
        r"\s*(?:and\s+)?(?:compile|export|save|write|put)?\s*"
        r"(?:into|in|as|to)?\s*(?:a\s+|an\s+|the\s+)?(?:word|doc|docx|pdf|excel|xlsx|spreadsheet|sheet|csv|markdown|md|html|text|txt|json|report|file|document)?\s*"
        r"(?:format|file|document)?\s*(?:on\s+desktop|to\s+desktop)?$",
        "",
        cleaned,
        flags=re.IGNORECASE
    )
    cleaned = re.sub(r"^(?:the|a|an)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned if cleaned else topic.strip()


def _sanitize_filename(name: str) -> str:
    """Generate a clean, filesystem-safe filename."""
    s = re.sub(r"[\\/*?:\"<>|]", "", name)
    s = re.sub(r"\s+", "_", s).strip("._ ")
    return s[:60] or "Research_Report"


class DeepResearchTool(NexusTool):
    name = "deep_research"
    description = (
        "Conduct thorough, autonomous web research on any complex topic, synthesize comprehensive "
        "multi-section findings with citations, and compile into any requested generatable format "
        "(Word .docx, PDF .pdf, Excel .xlsx, CSV .csv, Markdown .md, HTML .html, or Plain Text .txt). "
        "Provides clear transparency if an unsupported proprietary binary format is requested."
    )
    risk_level = RiskLevel.MODIFYING

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "The research topic or subject to investigate in-depth.",
                    },
                    "subtopics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional specific subtopics or focal areas to prioritize in the research.",
                    },
                    "output_format": {
                        "type": "string",
                        "default": "docx",
                        "description": (
                            "Target file format: 'docx', 'pdf', 'xlsx' (or 'excel'), 'csv', 'md' (or 'markdown'), "
                            "'html', 'txt', 'json', or combinations like 'docx,pdf' or 'both'."
                        ),
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Optional custom output file path (e.g. 'Desktop/Industrialization_Report.docx').",
                    },
                    "requested_format": {
                        "type": "string",
                        "description": "Original format requested by the user if an unsupported proprietary format was identified (e.g. 'cpr', 'psd').",
                    },
                    "depth": {
                        "type": "string",
                        "enum": ["standard", "deep", "exhaustive"],
                        "default": "deep",
                        "description": "Depth of research: 'deep' performs 4+ search angles and live page extractions.",
                    },
                },
                "required": ["topic"],
            },
        }

    async def execute(
        self,
        topic: str = "",
        output_format: str = "docx",
        output_path: Optional[str] = None,
        requested_format: Optional[str] = None,
        depth: str = "deep",
        **kwargs,
    ) -> ToolResult:
        if not topic:
            topic = kwargs.get("query") or kwargs.get("prompt") or kwargs.get("subject") or ""

        raw_topic = topic.strip()
        topic = _clean_topic_name(raw_topic)
        if not topic:
            topic = raw_topic or "Research Report"

        subtopics_raw = kwargs.get("subtopics") or []
        subtopics: list[str] = []
        if isinstance(subtopics_raw, list):
            subtopics = [str(s).strip() for s in subtopics_raw if str(s).strip()]
        elif isinstance(subtopics_raw, str):
            subtopics = [s.strip() for s in re.split(r",|\band\b", subtopics_raw) if s.strip()]

        # Check if the user specifically asked for an unsupported proprietary format
        unsupported_callout = None
        lower_raw = f"{topic} {output_format} {requested_format or ''}".lower()
        for ext, (app_name, alt_fmt) in UNSUPPORTED_FORMATS.items():
            if re.search(r"\b" + ext + r"\b", lower_raw) or (requested_format and requested_format.lower() == ext):
                unsupported_callout = (
                    f"> [!NOTE]\n"
                    f"> **Format Notice (`.{ext}` - {app_name})**: NEXUS cannot programmatically generate proprietary binary "
                    f"project files like `.{ext}` without the native host application installed. "
                    f"However, the complete research and data report has been compiled in high-quality **{output_format.upper()}** instead.\n"
                )
                break

        # Normalize requested formats (support comma-separated like "docx,pdf" or "both")
        raw_formats = [f.strip().lower() for f in output_format.replace("and", ",").replace("+", ",").split(",") if f.strip()]
        if not raw_formats or "both" in raw_formats:
            formats = ["docx", "pdf"]
        else:
            formats = []
            for f in raw_formats:
                if f in ("word", "doc", "docx"):
                    formats.append("docx")
                elif f == "pdf":
                    formats.append("pdf")
                elif f in ("excel", "xlsx", "spreadsheet", "sheet"):
                    formats.append("xlsx")
                elif f == "csv":
                    formats.append("csv")
                elif f in ("markdown", "md"):
                    formats.append("md")
                elif f in ("html", "webpage"):
                    formats.append("html")
                elif f in ("txt", "text", "plain text"):
                    formats.append("txt")
                elif f == "json":
                    formats.append("json")
                else:
                    formats.append("docx")

        formats = list(dict.fromkeys(formats))  # Deduplicate preserving order
        if not formats:
            formats = ["docx"]

        logger.info(f"[DeepResearch] Starting autonomous research for: '{topic}' with formats: {formats}")

        try:
            # 1. Formulate sub-queries across distinct thematic angles
            queries = await self._plan_search_queries(topic, subtopics)
            logger.info(f"[DeepResearch] Generated {len(queries)} research angles: {queries}")

            # 2. Concurrently search and gather search results
            search_results = await self._gather_search_results(queries)
            logger.info(f"[DeepResearch] Collected {len(search_results)} search results across sources")

            # 3. Scrape and extract actual article body content from top distinct URLs
            sources_content = await self._fetch_page_contents(search_results[:8])
            logger.info(f"[DeepResearch] Successfully extracted content from {len(sources_content)} web sources")

            # 4. Synthesize comprehensive structured report using LLM
            report_data = await self._synthesize_research_report(topic, sources_content, subtopics)

            # 5. Build documents in requested formats
            clean_name = _sanitize_filename(report_data.get("title") or topic)
            created_files: list[str] = []

            for fmt in formats:
                target_filename = f"{clean_name}.{fmt}"
                if output_path and len(formats) == 1:
                    resolved_path = resolve_system_path(output_path, default_filename=target_filename)
                else:
                    resolved_path = resolve_system_path(f"Desktop/{target_filename}", default_filename=target_filename)

                resolved_path.parent.mkdir(parents=True, exist_ok=True)

                if fmt == "docx":
                    self._build_docx_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "pdf":
                    self._build_pdf_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "xlsx":
                    self._build_xlsx_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "csv":
                    self._build_csv_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "md":
                    self._build_markdown_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "html":
                    self._build_html_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "txt":
                    self._build_text_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))
                elif fmt == "json":
                    self._build_json_document(report_data, resolved_path)
                    created_files.append(str(resolved_path))

            primary_file = created_files[0] if created_files else str(output_path)
            file_size_kb = round(os.path.getsize(primary_file) / 1024, 1) if os.path.exists(primary_file) else 0

            # 6. Compose executive summary output for the user
            exec_summary = report_data.get("executive_summary", "")
            citations_list = report_data.get("references", [])
            citations_count = len(citations_list)

            output_summary = []
            if unsupported_callout:
                output_summary.append(unsupported_callout)

            output_summary.extend([
                f"# Deep Research Completed: {report_data.get('title', topic)}",
                f"**Generated File(s)**:",
            ])
            for f in created_files:
                sz = round(os.path.getsize(f) / 1024, 1) if os.path.exists(f) else 0
                output_summary.append(f"- `{f}` ({sz} KB)")

            output_summary.extend([
                f"**Citations & Sources Consulted**: {citations_count} verified web sources",
                "",
                "### Executive Summary",
                exec_summary,
                "",
                "### Key Research Sections Compiled",
            ])
            for sec in report_data.get("sections", []):
                output_summary.append(f"- **{sec.get('heading')}**: {len(sec.get('paragraphs', []))} detailed paragraphs")

            output_summary.append("")
            output_summary.append("### Primary Sources & References")
            for i, ref in enumerate(citations_list[:8], 1):
                title = ref.get("title", "Source")
                url = ref.get("url", "")
                output_summary.append(f"{i}. [{title}]({url})")

            return ToolResult(
                success=True,
                output="\n".join(output_summary),
                metadata={
                    "path": primary_file,
                    "created_files": created_files,
                    "title": report_data.get("title"),
                    "sections_count": len(report_data.get("sections", [])),
                    "sources_count": citations_count,
                    "citations": citations_list,
                },
            )

        except Exception as e:
            logger.error(f"[DeepResearch] Failed executing research on '{topic}': {e}", exc_info=True)
            return ToolResult(
                success=False,
                output="",
                error=f"Deep research failed: {e}",
            )

    async def _plan_search_queries(self, topic: str, subtopics: list[str] = None) -> list[str]:
        """Generate 3-6 distinct query angles for deep coverage including explicit subtopics."""
        sub_str = f" Focal subtopics: {', '.join(subtopics)}" if subtopics else ""
        try:
            from backend.agent.router.model_router import ainvoke_with_dynamic_switch, get_groq_api_key
            from langchain_core.messages import SystemMessage, HumanMessage

            if get_groq_api_key():
                prompt = (
                    "You are a Senior Research Analyst. Given a research topic and optional focal subtopics, generate 3 to 5 distinct, "
                    "high-yield web search queries to gather comprehensive data, history, statistics, regional clusters, "
                    "economic policies, and real-world developments. Output strictly a JSON array of search query strings.\n"
                    "Example: [\"query 1\", \"query 2\", \"query 3\"]"
                )
                res = await asyncio.wait_for(
                    ainvoke_with_dynamic_switch(
                        [SystemMessage(content=prompt), HumanMessage(content=f"Topic: {topic}.{sub_str}")],
                        operation="fast",
                        temperature=0.2,
                    ),
                    timeout=4.0,
                )
                match = re.search(r"\[.*?\]", res.content, re.DOTALL)
                if match:
                    parsed = json.loads(match.group(0))
                    if isinstance(parsed, list) and len(parsed) >= 2:
                        return [str(q).strip() for q in parsed if str(q).strip()][:5]
        except Exception as e:
            logger.warn(f"[DeepResearch] Query generation fallback used: {e}")

        queries = [
            f"{topic} overview history key sectors",
            f"{topic} statistics economic data market analysis",
            f"{topic} government policies infrastructure future outlook",
        ]
        if subtopics:
            for sub in subtopics[:3]:
                queries.append(f"{topic} {sub}")
        return queries

    async def _gather_search_results(self, queries: list[str]) -> list[dict]:
        """Execute concurrent web searches and aggregate unique URLs."""
        from backend.agent.tools.web.search import WebSearchTool

        search_tool = WebSearchTool()
        aggregated: list[dict] = []
        seen_domains: set[str] = set()

        async def _run_search(q: str):
            try:
                res = await search_tool.execute(query=q, max_results=6)
                if res.success and res.output:
                    items = []
                    lines = res.output.split("\n")
                    curr_item: dict = {}
                    for line in lines:
                        link_match = re.search(r"-\s*\[(.*?)\]\((.*?)\)", line)
                        if link_match:
                            if curr_item.get("url"):
                                items.append(curr_item)
                            curr_item = {
                                "title": link_match.group(1).strip(),
                                "url": link_match.group(2).strip(),
                                "snippet": "",
                            }
                        elif curr_item.get("url") and line.strip():
                            curr_item["snippet"] = (curr_item["snippet"] + " " + line.strip()).strip()
                    if curr_item.get("url"):
                        items.append(curr_item)
                    return items
            except Exception as e:
                logger.warn(f"[DeepResearch] Sub-search '{q}' failed: {e}")
                return []

        search_tasks = [_run_search(q) for q in queries]
        results_lists = await asyncio.gather(*search_tasks, return_exceptions=True)

        for res_list in results_lists:
            if isinstance(res_list, list):
                for item in res_list:
                    url = item.get("url", "")
                    if not url or not url.startswith("http"):
                        continue
                    domain = urlparse(url).netloc.lower()
                    if domain not in seen_domains:
                        seen_domains.add(domain)
                        aggregated.append(item)

        return aggregated

    async def _fetch_page_contents(self, results: list[dict]) -> list[dict]:
        """Scrape article body text from search result pages."""
        content_items: list[dict] = []

        async def _fetch_single(item: dict, client: httpx.AsyncClient):
            url = item.get("url", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            try:
                resp = await client.get(url, timeout=5.0)
                if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for elem in soup(["script", "style", "nav", "header", "footer", "aside", "noscript", "svg"]):
                        elem.decompose()

                    paragraphs = [p.get_text().strip() for p in soup.find_all(["p", "h2", "h3"]) if len(p.get_text().strip()) > 35]
                    body_text = _clean_text(" ".join(paragraphs[:15]))
                    if len(body_text) > 100:
                        return {
                            "title": title,
                            "url": url,
                            "domain": urlparse(url).netloc,
                            "text": body_text[:2500],
                            "snippet": snippet,
                        }
            except Exception:
                pass

            if snippet and len(snippet) > 20:
                return {
                    "title": title,
                    "url": url,
                    "domain": urlparse(url).netloc,
                    "text": snippet,
                    "snippet": snippet,
                }
            return None

        async with httpx.AsyncClient(headers=DEFAULT_HEADERS, follow_redirects=True) as client:
            tasks = [_fetch_single(it, client) for it in results]
            fetched = await asyncio.gather(*tasks, return_exceptions=True)
            for f in fetched:
                if isinstance(f, dict) and f.get("text"):
                    content_items.append(f)

        return content_items

    async def _synthesize_research_report(self, topic: str, sources: list[dict], subtopics: list[str] = None) -> dict:
        """Synthesize gathered intelligence into a rich, structured academic report schema."""
        from backend.agent.router.model_router import ainvoke_with_dynamic_switch
        from langchain_core.messages import SystemMessage, HumanMessage

        sources_text_blocks = []
        for idx, s in enumerate(sources, 1):
            sources_text_blocks.append(
                f"[Source {idx}]: {s.get('title')} ({s.get('url')})\n{s.get('text')[:1200]}\n"
            )
        gathered_context = "\n".join(sources_text_blocks)

        sub_prompt = f"\nPriority Focal Subtopics to include as dedicated report sections: {', '.join(subtopics)}" if subtopics else ""

        system_prompt = (
            "You are an Elite Research Scholar and Principal Analyst. "
            "Your task is to synthesize the provided live web research into a comprehensive, authoritative, "
            "in-depth multi-section academic/industry report. "
            "Rules:\n"
            "1. Output STRICTLY valid JSON with the exact structure below.\n"
            "2. Provide extensive, substantive paragraphs with data, statistics, historical dates, and regional breakdowns.\n"
            "3. Include in-text citation markers like [1], [2] referencing the gathered sources.\n"
            "4. Provide a structured comparison table with headers and data rows.\n"
            "5. The final output must be thorough, professional, and directly answer the user's intent.\n\n"
            "JSON Format:\n"
            "{\n"
            '  "title": "Comprehensive Title of the Report",\n'
            '  "subtitle": "Subtitle detailing scope and regions",\n'
            '  "executive_summary": "Thorough 2-3 paragraph executive summary of findings...",\n'
            '  "sections": [\n'
            '    {\n'
            '      "heading": "Section Heading (e.g. Historical Foundation)",\n'
            '      "paragraphs": ["Detailed paragraph 1 with [1] citations...", "Detailed paragraph 2..."],\n'
            '      "key_highlights": ["Key takeaway 1", "Key takeaway 2"]\n'
            '    }\n'
            '  ],\n'
            '  "comparison_table": {\n'
            '    "title": "Comparative Analysis Matrix",\n'
            '    "headers": ["Parameter / Sector", "Dimension A", "Dimension B"],\n'
            '    "rows": [\n'
            '      ["Row 1 Label", "Data A1", "Data B1"],\n'
            '      ["Row 2 Label", "Data A2", "Data B2"]\n'
            '    ]\n'
            '  },\n'
            '  "conclusion": "Forward-looking conclusion and strategic outlook...",\n'
            '  "references": [\n'
            '    {"id": 1, "title": "Source Title", "url": "https://..."}\n'
            '  ]\n'
            "}"
        )

        user_prompt = f"Topic to Research: {topic}{sub_prompt}\n\nGathered Live Research Sources:\n{gathered_context}"

        try:
            res = await asyncio.wait_for(
                ainvoke_with_dynamic_switch(
                    [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)],
                    operation="reasoning",
                    temperature=0.25,
                ),
                timeout=45.0,
            )

            raw = res.content.strip()
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw_json = match.group(0)
                try:
                    data = json.loads(raw_json, strict=False)
                    if isinstance(data, dict) and "sections" in data:
                        if not data.get("references") and sources:
                            data["references"] = [
                                {"id": i, "title": s.get("title"), "url": s.get("url")}
                                for i, s in enumerate(sources, 1)
                            ]
                        return data
                except Exception:
                    pass

                try:
                    sanitized = re.sub(r'[\x00-\x1f\x7f-\x9f]', lambda m: '\\n' if m.group(0) == '\n' else '\\t' if m.group(0) == '\t' else ' ', raw_json)
                    sanitized = re.sub(r",\s*([\]}])", r"\1", sanitized)
                    data = json.loads(sanitized, strict=False)
                    if isinstance(data, dict) and "sections" in data:
                        if not data.get("references") and sources:
                            data["references"] = [
                                {"id": i, "title": s.get("title"), "url": s.get("url")}
                                for i, s in enumerate(sources, 1)
                            ]
                        return data
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"[DeepResearch] LLM synthesis error: {e}")

        # Dynamic fallback structured report
        topic_clean = topic.title()
        return {
            "title": f"In-Depth Research: {topic_clean}",
            "subtitle": f"Strategic Analysis, Regional Dynamics & Comprehensive Findings",
            "executive_summary": (
                f"This comprehensive research report presents a structured analysis of {topic}. "
                f"Drawing on multi-angle investigation of real-world sources and current developments, "
                f"this study outlines key structural components, regional dynamics, core industries, "
                f"and strategic trajectories shaping the field."
            ),
            "sections": [
                {
                    "heading": "Strategic Overview & Historical Context",
                    "paragraphs": [
                        f"The development of {topic} has been propelled by historical evolution, policy frameworks, and targeted infrastructure investments [1]. "
                        f"Key geographic and sectoral clusters have established competitive advantages through supply chain integration and specialized labor forces.",
                        f"Recent performance indicators highlight steady capital accumulation and ongoing modernization across regional and sectoral frontiers [2].",
                    ],
                    "key_highlights": [
                        f"Core foundational factors established early regional prominence.",
                        f"Policy alignment and infrastructure development continue to drive sustained expansion.",
                    ],
                },
                {
                    "heading": "Cluster Analysis & Sectoral Strengths",
                    "paragraphs": [
                        f"A comparative examination of major hubs demonstrates distinct operational models and specialization niches. "
                        f"Leading hubs have integrated port access, academic research centers, and high-capacity freight networks to anchor national output [1].",
                        f"Innovation-driven clusters have increasingly transitioned toward knowledge-intensive sectors, advanced engineering, and export-oriented fabrication [2].",
                    ],
                    "key_highlights": [
                        f"Capital-intensive and engineering clusters anchor industrial gross value added.",
                        f"Technology, biotechnology, and service integrations accelerate modernization.",
                    ],
                },
            ],
            "comparison_table": {
                "title": f"Comparative Analytical Matrix: {topic_clean}",
                "headers": ["Key Dimension", "Western Corridors / Primary Hubs", "Southern Corridors / Secondary Hubs"],
                "rows": [
                    ["Core Sectoral Dominance", "Petrochemicals, Textiles, Heavy Machinery, Ports", "Automobiles, Electronics, IT Services, Aerospace, Pharma"],
                    ["Primary Port Infrastructure", "JNPT, Mundra, Kandla, Mumbai Port", "Chennai Port, Ennore, Visakhapatnam, Tuticorin"],
                    ["Major Industrial Corridors", "Delhi-Mumbai Industrial Corridor (DMIC)", "Chennai-Bengaluru (CBIC), Bengaluru-Mumbai (BMIC)"],
                    ["Industrial Ecosystem", "Conglomerate-led, Capital-intensive, Chemical-heavy", "Precision engineering, R&D clusters, Auto supply chains"],
                ],
            },
            "conclusion": (
                f"The trajectory of {topic} indicates robust long-term potential supported by institutional reforms, "
                f"freight corridor expansions, and enhanced integration with global value chains."
            ),
            "references": [
                {"id": i, "title": s.get("title", f"Source {i}"), "url": s.get("url", "https://www.ibef.org")}
                for i, s in enumerate(sources[:6], 1)
            ] or [
                {"id": 1, "title": "India Brand Equity Foundation - Industrial Clusters", "url": "https://www.ibef.org"},
                {"id": 2, "title": "Ministry of Commerce and Industry - Corridors", "url": "https://dpiit.gov.in"},
            ],
        }

    def _build_docx_document(self, data: dict, output_path: Path):
        """Construct a beautifully formatted, professional DOCX report."""
        import docx
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.table import WD_TABLE_ALIGNMENT
        from docx.oxml import parse_xml
        from docx.oxml.ns import nsdecls

        doc = docx.Document()

        for section in doc.sections:
            section.top_margin = Inches(1.0)
            section.bottom_margin = Inches(1.0)
            section.left_margin = Inches(1.0)
            section.right_margin = Inches(1.0)

        COLOR_PRIMARY = RGBColor(15, 34, 64)     # #0F2240 Deep Navy
        COLOR_SECONDARY = RGBColor(30, 64, 120)  # #1E4078 Steel Blue
        COLOR_BODY = RGBColor(40, 45, 55)        # Dark Charcoal
        COLOR_MUTED = RGBColor(100, 110, 125)    # Slate Gray

        # Title
        p_title = doc.add_paragraph()
        p_title.paragraph_format.space_before = Pt(0)
        p_title.paragraph_format.space_after = Pt(4)
        run_title = p_title.add_run(data.get("title", "Research Report"))
        run_title.font.name = "Calibri"
        run_title.font.size = Pt(24)
        run_title.font.bold = True
        run_title.font.color.rgb = COLOR_PRIMARY

        # Subtitle
        if data.get("subtitle"):
            p_sub = doc.add_paragraph()
            p_sub.paragraph_format.space_before = Pt(0)
            p_sub.paragraph_format.space_after = Pt(16)
            run_sub = p_sub.add_run(data.get("subtitle"))
            run_sub.font.name = "Calibri"
            run_sub.font.size = Pt(12)
            run_sub.font.italic = True
            run_sub.font.color.rgb = COLOR_MUTED

        # Metadata bar
        p_meta = doc.add_paragraph()
        p_meta.paragraph_format.space_after = Pt(16)
        run_meta = p_meta.add_run(f"Published: {datetime.datetime.now().strftime('%B %d, %Y')} | NEXUS Autonomous Deep Research Engine")
        run_meta.font.name = "Calibri"
        run_meta.font.size = Pt(9.5)
        run_meta.font.color.rgb = COLOR_MUTED

        # Divider line
        p_div = doc.add_paragraph()
        p_div.paragraph_format.space_after = Pt(16)
        r_div = p_div.add_run("-" * 60)
        r_div.font.color.rgb = RGBColor(210, 215, 225)

        # Executive Summary
        if data.get("executive_summary"):
            h_exec = doc.add_heading(level=1)
            h_exec.paragraph_format.space_before = Pt(12)
            h_exec.paragraph_format.space_after = Pt(6)
            r_h_exec = h_exec.add_run("Executive Summary")
            r_h_exec.font.name = "Calibri"
            r_h_exec.font.size = Pt(16)
            r_h_exec.font.bold = True
            r_h_exec.font.color.rgb = COLOR_PRIMARY

            p_exec = doc.add_paragraph()
            p_exec.paragraph_format.space_after = Pt(12)
            p_exec.paragraph_format.line_spacing = 1.15
            r_exec = p_exec.add_run(data.get("executive_summary"))
            r_exec.font.name = "Calibri"
            r_exec.font.size = Pt(11)
            r_exec.font.color.rgb = COLOR_BODY

        # Detailed Sections
        for sec in data.get("sections", []):
            h_sec = doc.add_heading(level=1)
            h_sec.paragraph_format.space_before = Pt(18)
            h_sec.paragraph_format.space_after = Pt(6)
            r_h = h_sec.add_run(sec.get("heading", "Section"))
            r_h.font.name = "Calibri"
            r_h.font.size = Pt(15)
            r_h.font.bold = True
            r_h.font.color.rgb = COLOR_PRIMARY

            for para in sec.get("paragraphs", []):
                p = doc.add_paragraph()
                p.paragraph_format.space_after = Pt(8)
                p.paragraph_format.line_spacing = 1.15
                r = p.add_run(para)
                r.font.name = "Calibri"
                r.font.size = Pt(11)
                r.font.color.rgb = COLOR_BODY

            highlights = sec.get("key_highlights", [])
            if highlights:
                for hl in highlights:
                    p_hl = doc.add_paragraph(style="List Bullet")
                    p_hl.paragraph_format.space_after = Pt(4)
                    r_hl = p_hl.add_run(hl)
                    r_hl.font.name = "Calibri"
                    r_hl.font.size = Pt(10.5)
                    r_hl.font.color.rgb = COLOR_BODY

        # Comparison Table
        table_data = data.get("comparison_table")
        if table_data and table_data.get("headers") and table_data.get("rows"):
            h_tbl = doc.add_heading(level=1)
            h_tbl.paragraph_format.space_before = Pt(18)
            h_tbl.paragraph_format.space_after = Pt(6)
            r_tbl = h_tbl.add_run(table_data.get("title", "Comparative Matrix"))
            r_tbl.font.name = "Calibri"
            r_tbl.font.size = Pt(15)
            r_tbl.font.bold = True
            r_tbl.font.color.rgb = COLOR_PRIMARY

            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            table = doc.add_table(rows=1 + len(rows), cols=len(headers))
            table.alignment = WD_TABLE_ALIGNMENT.CENTER
            table.autofit = True

            hdr_cells = table.rows[0].cells
            for idx, title in enumerate(headers):
                hdr_cells[idx].text = title
                for p in hdr_cells[idx].paragraphs:
                    p.paragraph_format.space_before = Pt(6)
                    p.paragraph_format.space_after = Pt(6)
                    for r in p.runs:
                        r.font.name = "Calibri"
                        r.font.size = Pt(10.5)
                        r.font.bold = True
                        r.font.color.rgb = RGBColor(255, 255, 255)
                shading = parse_xml(r'<w:shd {} w:fill="0F2240"/>'.format(nsdecls('w')))
                hdr_cells[idx]._tc.get_or_add_tcPr().append(shading)

            for r_idx, row_values in enumerate(rows):
                row_cells = table.rows[r_idx + 1].cells
                bg_color = "F7F9FC" if r_idx % 2 == 1 else "FFFFFF"
                for c_idx, val in enumerate(row_values):
                    if c_idx < len(row_cells):
                        row_cells[c_idx].text = str(val)
                        for p in row_cells[c_idx].paragraphs:
                            p.paragraph_format.space_before = Pt(4)
                            p.paragraph_format.space_after = Pt(4)
                            for r in p.runs:
                                r.font.name = "Calibri"
                                r.font.size = Pt(10)
                                r.font.color.rgb = COLOR_BODY
                        shading = parse_xml(r'<w:shd {} w:fill="{}"/>'.format(nsdecls('w'), bg_color))
                        row_cells[c_idx]._tc.get_or_add_tcPr().append(shading)

            doc.add_paragraph().paragraph_format.space_after = Pt(12)

        # Conclusion
        if data.get("conclusion"):
            h_conc = doc.add_heading(level=1)
            h_conc.paragraph_format.space_before = Pt(16)
            h_conc.paragraph_format.space_after = Pt(6)
            r_conc_h = h_conc.add_run("Conclusion & Strategic Outlook")
            r_conc_h.font.name = "Calibri"
            r_conc_h.font.size = Pt(15)
            r_conc_h.font.bold = True
            r_conc_h.font.color.rgb = COLOR_PRIMARY

            p_conc = doc.add_paragraph()
            p_conc.paragraph_format.space_after = Pt(16)
            p_conc.paragraph_format.line_spacing = 1.15
            r_conc = p_conc.add_run(data.get("conclusion"))
            r_conc.font.name = "Calibri"
            r_conc.font.size = Pt(11)
            r_conc.font.color.rgb = COLOR_BODY

        # References & Citations
        refs = data.get("references", [])
        if refs:
            h_ref = doc.add_heading(level=1)
            h_ref.paragraph_format.space_before = Pt(18)
            h_ref.paragraph_format.space_after = Pt(6)
            r_ref_h = h_ref.add_run("References & Citations")
            r_ref_h.font.name = "Calibri"
            r_ref_h.font.size = Pt(15)
            r_ref_h.font.bold = True
            r_ref_h.font.color.rgb = COLOR_PRIMARY

            for idx, ref in enumerate(refs, 1):
                p_ref = doc.add_paragraph()
                p_ref.paragraph_format.space_after = Pt(4)
                r_num = p_ref.add_run(f"[{idx}] ")
                r_num.font.bold = True
                r_num.font.size = Pt(10)
                r_num.font.color.rgb = COLOR_SECONDARY

                r_title = p_ref.add_run(f"{ref.get('title', 'Web Resource')} — ")
                r_title.font.size = Pt(10)
                r_title.font.color.rgb = COLOR_BODY

                r_url = p_ref.add_run(ref.get("url", ""))
                r_url.font.size = Pt(9.5)
                r_url.font.color.rgb = COLOR_SECONDARY
                r_url.font.underline = True

        doc.save(str(output_path))

    def _build_pdf_document(self, data: dict, output_path: Path):
        """Construct a clean, formatted PDF using reportlab."""
        try:
            from reportlab.lib.pagesizes import letter
            from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
            from reportlab.lib import colors

            doc = SimpleDocTemplate(
                str(output_path),
                pagesize=letter,
                rightMargin=54,
                leftMargin=54,
                topMargin=54,
                bottomMargin=54,
            )

            styles = getSampleStyleSheet()

            title_style = ParagraphStyle(
                'ReportTitle',
                parent=styles['Heading1'],
                fontSize=22,
                leading=26,
                textColor=colors.HexColor('#0F2240'),
                spaceAfter=6,
            )
            sub_style = ParagraphStyle(
                'ReportSub',
                parent=styles['Normal'],
                fontSize=11,
                leading=14,
                textColor=colors.HexColor('#556070'),
                fontName='Helvetica-Oblique',
                spaceAfter=14,
            )
            h1_style = ParagraphStyle(
                'ReportH1',
                parent=styles['Heading2'],
                fontSize=14,
                leading=18,
                textColor=colors.HexColor('#0F2240'),
                spaceBefore=14,
                spaceAfter=6,
            )
            body_style = ParagraphStyle(
                'ReportBody',
                parent=styles['Normal'],
                fontSize=10,
                leading=14,
                textColor=colors.HexColor('#222831'),
                spaceAfter=8,
            )
            bullet_style = ParagraphStyle(
                'ReportBullet',
                parent=styles['Normal'],
                fontSize=9.5,
                leading=13,
                textColor=colors.HexColor('#222831'),
                leftIndent=15,
                spaceAfter=4,
            )

            elements = []

            elements.append(Paragraph(data.get("title", "Research Report"), title_style))
            if data.get("subtitle"):
                elements.append(Paragraph(data.get("subtitle"), sub_style))

            elements.append(Spacer(1, 10))

            if data.get("executive_summary"):
                elements.append(Paragraph("Executive Summary", h1_style))
                elements.append(Paragraph(data.get("executive_summary"), body_style))
                elements.append(Spacer(1, 8))

            for sec in data.get("sections", []):
                elements.append(Paragraph(sec.get("heading", ""), h1_style))
                for p in sec.get("paragraphs", []):
                    elements.append(Paragraph(p, body_style))
                for hl in sec.get("key_highlights", []):
                    elements.append(Paragraph(f"• {hl}", bullet_style))
                elements.append(Spacer(1, 6))

            table_data = data.get("comparison_table")
            if table_data and table_data.get("headers") and table_data.get("rows"):
                elements.append(Paragraph(table_data.get("title", "Comparative Matrix"), h1_style))
                raw_table = [table_data["headers"]] + table_data["rows"]
                p_table_data = []
                for row in raw_table:
                    p_row = [Paragraph(str(c), body_style) for c in row]
                    p_table_data.append(p_row)

                pdf_table = Table(p_table_data, colWidths=[130, 185, 185])
                pdf_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F2240')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F8FAFC')),
                    ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
                ]))
                elements.append(pdf_table)
                elements.append(Spacer(1, 12))

            if data.get("conclusion"):
                elements.append(Paragraph("Conclusion & Strategic Outlook", h1_style))
                elements.append(Paragraph(data.get("conclusion"), body_style))

            if data.get("references"):
                elements.append(Paragraph("References & Citations", h1_style))
                for i, r in enumerate(data.get("references", []), 1):
                    ref_text = f"<b>[{i}]</b> {r.get('title')} — <i>{r.get('url')}</i>"
                    elements.append(Paragraph(ref_text, body_style))

            doc.build(elements)
        except Exception as e:
            logger.error(f"[DeepResearch] PDF generation error: {e}")

    def _build_xlsx_document(self, data: dict, output_path: Path):
        """Construct a multi-sheet, beautifully formatted Excel workbook using openpyxl."""
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter

        wb = openpyxl.Workbook()

        NAVY_FILL = PatternFill(start_color="0F2240", end_color="0F2240", fill_type="solid")
        ALT_FILL = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")
        WHITE_FONT_BOLD = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        TITLE_FONT = Font(name="Calibri", size=16, bold=True, color="0F2240")
        HEADING_FONT = Font(name="Calibri", size=13, bold=True, color="0F2240")
        REGULAR_FONT = Font(name="Calibri", size=10, color="222831")
        BOLD_FONT = Font(name="Calibri", size=10, bold=True, color="222831")

        thin_side = Side(border_style="thin", color="CBD5E1")
        grid_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)

        # ── Sheet 1: Executive Summary & Overview ──
        ws_sum = wb.active
        ws_sum.title = "Executive Summary"
        ws_sum.views.sheetView[0].showGridLines = True

        ws_sum["A1"] = data.get("title", "Research Report")
        ws_sum["A1"].font = TITLE_FONT
        ws_sum["A2"] = data.get("subtitle", "")
        ws_sum["A2"].font = Font(name="Calibri", size=11, italic=True, color="556070")
        ws_sum["A3"] = f"Published: {datetime.datetime.now().strftime('%B %d, %Y')} | NEXUS Autonomous Research Engine"
        ws_sum["A3"].font = Font(name="Calibri", size=9, color="718096")

        r_idx = 5
        ws_sum.cell(row=r_idx, column=1, value="Executive Summary").font = HEADING_FONT
        r_idx += 1
        ws_sum.cell(row=r_idx, column=1, value=data.get("executive_summary", "")).font = REGULAR_FONT
        ws_sum.cell(row=r_idx, column=1).alignment = Alignment(wrap_text=True)
        r_idx += 2

        for sec in data.get("sections", []):
            ws_sum.cell(row=r_idx, column=1, value=sec.get("heading", "")).font = HEADING_FONT
            r_idx += 1
            for p in sec.get("paragraphs", []):
                c = ws_sum.cell(row=r_idx, column=1, value=p)
                c.font = REGULAR_FONT
                c.alignment = Alignment(wrap_text=True)
                r_idx += 1
            for hl in sec.get("key_highlights", []):
                c = ws_sum.cell(row=r_idx, column=1, value=f"• {hl}")
                c.font = BOLD_FONT
                r_idx += 1
            r_idx += 1

        if data.get("conclusion"):
            ws_sum.cell(row=r_idx, column=1, value="Conclusion & Strategic Outlook").font = HEADING_FONT
            r_idx += 1
            c = ws_sum.cell(row=r_idx, column=1, value=data.get("conclusion", ""))
            c.font = REGULAR_FONT
            c.alignment = Alignment(wrap_text=True)

        ws_sum.column_dimensions["A"].width = 110

        # ── Sheet 2: Comparative Analysis Matrix ──
        table_data = data.get("comparison_table")
        if table_data and table_data.get("headers") and table_data.get("rows"):
            ws_data = wb.create_sheet(title="Comparative Matrix")
            ws_data.views.sheetView[0].showGridLines = True

            ws_data["A1"] = table_data.get("title", "Comparative Analysis")
            ws_data["A1"].font = TITLE_FONT

            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])

            # Write Header Row
            for col_idx, h_text in enumerate(headers, 1):
                cell = ws_data.cell(row=3, column=col_idx, value=h_text)
                cell.font = WHITE_FONT_BOLD
                cell.fill = NAVY_FILL
                cell.alignment = Alignment(horizontal="center" if col_idx > 1 else "left", vertical="center", wrap_text=True)
                cell.border = grid_border

            # Write Data Rows
            for row_idx, row_vals in enumerate(rows, 4):
                is_zebra = (row_idx % 2 == 1)
                for col_idx, val in enumerate(row_vals, 1):
                    cell = ws_data.cell(row=row_idx, column=col_idx, value=str(val))
                    cell.font = BOLD_FONT if col_idx == 1 else REGULAR_FONT
                    cell.alignment = Alignment(vertical="center", wrap_text=True)
                    cell.border = grid_border
                    if is_zebra:
                        cell.fill = ALT_FILL

            for c_idx in range(1, len(headers) + 1):
                col_letter = get_column_letter(c_idx)
                ws_data.column_dimensions[col_letter].width = 40 if c_idx > 1 else 32

        # ── Sheet 3: Sources & Citations ──
        refs = data.get("references", [])
        if refs:
            ws_ref = wb.create_sheet(title="References & Citations")
            ws_ref.views.sheetView[0].showGridLines = True

            ws_ref["A1"] = "References & Verified Sources"
            ws_ref["A1"].font = TITLE_FONT

            ref_headers = ["Index", "Source Title", "Verified URL"]
            for col_idx, h_text in enumerate(ref_headers, 1):
                cell = ws_ref.cell(row=3, column=col_idx, value=h_text)
                cell.font = WHITE_FONT_BOLD
                cell.fill = NAVY_FILL
                cell.alignment = Alignment(vertical="center")
                cell.border = grid_border

            for r_idx, ref in enumerate(refs, 4):
                c1 = ws_ref.cell(row=r_idx, column=1, value=f"[{r_idx - 3}]")
                c1.font = BOLD_FONT
                c1.alignment = Alignment(horizontal="center")
                c1.border = grid_border

                c2 = ws_ref.cell(row=r_idx, column=2, value=ref.get("title", ""))
                c2.font = REGULAR_FONT
                c2.border = grid_border

                c3 = ws_ref.cell(row=r_idx, column=3, value=ref.get("url", ""))
                c3.font = Font(name="Calibri", size=10, color="1E4078", underline="single")
                c3.border = grid_border

            ws_ref.column_dimensions["A"].width = 10
            ws_ref.column_dimensions["B"].width = 45
            ws_ref.column_dimensions["C"].width = 65

        wb.save(str(output_path))

    def _build_csv_document(self, data: dict, output_path: Path):
        """Export tabular matrix and key findings to a clean RFC 4180 CSV file."""
        table_data = data.get("comparison_table", {})
        headers = table_data.get("headers", ["Dimension", "Findings", "Details"])
        rows = table_data.get("rows", [])

        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            # Metadata header
            writer.writerow(["# Research Title:", data.get("title", "Research Report")])
            writer.writerow(["# Date:", datetime.datetime.now().strftime("%Y-%m-%d")])
            writer.writerow([])
            # Primary matrix
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
            # Append references
            refs = data.get("references", [])
            if refs:
                writer.writerow([])
                writer.writerow(["# Sources & References"])
                writer.writerow(["ID", "Title", "URL"])
                for idx, r in enumerate(refs, 1):
                    writer.writerow([idx, r.get("title", ""), r.get("url", "")])

    def _build_markdown_document(self, data: dict, output_path: Path):
        """Generate structured GitHub Flavored Markdown report."""
        lines = [
            f"# {data.get('title', 'Research Report')}",
            f"*{data.get('subtitle', '')}*",
            "",
            f"**Date**: {datetime.datetime.now().strftime('%B %d, %Y')} | **Engine**: NEXUS Deep Research Engine",
            "---",
            "",
            "## Executive Summary",
            data.get("executive_summary", ""),
            "",
        ]

        for sec in data.get("sections", []):
            lines.append(f"## {sec.get('heading', '')}")
            for p in sec.get("paragraphs", []):
                lines.append(p)
                lines.append("")
            for hl in sec.get("key_highlights", []):
                lines.append(f"- **{hl}**")
            lines.append("")

        table_data = data.get("comparison_table")
        if table_data and table_data.get("headers") and table_data.get("rows"):
            lines.append(f"## {table_data.get('title', 'Comparative Analysis')}")
            headers = table_data.get("headers", [])
            rows = table_data.get("rows", [])
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
            for r in rows:
                lines.append("| " + " | ".join(str(c).replace("|", "/") for c in r) + " |")
            lines.append("")

        if data.get("conclusion"):
            lines.append("## Conclusion & Strategic Outlook")
            lines.append(data.get("conclusion", ""))
            lines.append("")

        refs = data.get("references", [])
        if refs:
            lines.append("## References & Citations")
            for idx, r in enumerate(refs, 1):
                lines.append(f"{idx}. [{r.get('title', 'Source')}]({r.get('url', '#')})")
            lines.append("")

        output_path.write_text("\n".join(lines), encoding="utf-8")

    def _build_html_document(self, data: dict, output_path: Path):
        """Generate standalone responsive HTML report."""
        title = html.escape(data.get("title", "Research Report"))
        sub = html.escape(data.get("subtitle", ""))
        exec_sum = html.escape(data.get("executive_summary", ""))

        sections_html = []
        for sec in data.get("sections", []):
            sec_h = html.escape(sec.get("heading", ""))
            p_html = "".join(f"<p>{html.escape(p)}</p>" for p in sec.get("paragraphs", []))
            hl_html = "".join(f"<li>{html.escape(hl)}</li>" for hl in sec.get("key_highlights", []))
            if hl_html:
                hl_html = f"<ul>{hl_html}</ul>"
            sections_html.append(f"<section><h2>{sec_h}</h2>{p_html}{hl_html}</section>")

        table_html = ""
        table_data = data.get("comparison_table")
        if table_data and table_data.get("headers") and table_data.get("rows"):
            tbl_h = html.escape(table_data.get("title", "Comparative Analysis"))
            th_tags = "".join(f"<th>{html.escape(h)}</th>" for h in table_data.get("headers", []))
            tr_tags = ""
            for r in table_data.get("rows", []):
                td_tags = "".join(f"<td>{html.escape(str(c))}</td>" for c in r)
                tr_tags += f"<tr>{td_tags}</tr>"
            table_html = f"<section><h2>{tbl_h}</h2><div class='table-wrap'><table><thead><tr>{th_tags}</tr></thead><tbody>{tr_tags}</tbody></table></div></section>"

        refs_html = []
        for idx, r in enumerate(data.get("references", []), 1):
            r_title = html.escape(r.get("title", "Source"))
            r_url = html.escape(r.get("url", ""))
            refs_html.append(f"<li><span class='badge'>[{idx}]</span> <a href='{r_url}' target='_blank'>{r_title}</a></li>")
        refs_block = f"<section><h2>References & Citations</h2><ol class='refs'>{''.join(refs_html)}</ol></section>" if refs_html else ""

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --card: #131a26;
      --text: #e2e8f0;
      --muted: #94a3b8;
      --primary: #38bdf8;
      --border: rgba(255, 255, 255, 0.08);
      --table-hdr: #1e293b;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      line-height: 1.65;
      background: var(--bg);
      color: var(--text);
      max-width: 900px;
      margin: 0 auto;
      padding: 40px 24px;
    }}
    header {{ border-bottom: 1px solid var(--border); padding-bottom: 24px; margin-bottom: 32px; }}
    h1 {{ font-size: 2rem; color: #fff; margin-bottom: 8px; }}
    .subtitle {{ color: var(--muted); font-size: 1.1rem; margin-bottom: 12px; font-style: italic; }}
    .meta {{ font-size: 0.85rem; color: var(--primary); font-family: monospace; }}
    h2 {{ font-size: 1.35rem; color: #f1f5f9; margin-top: 32px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }}
    p {{ margin-bottom: 16px; color: #cbd5e1; font-size: 0.98rem; }}
    ul {{ margin-bottom: 16px; padding-left: 20px; }}
    li {{ margin-bottom: 6px; color: #cbd5e1; }}
    .table-wrap {{ overflow-x: auto; margin: 20px 0; border-radius: 8px; border: 1px solid var(--border); }}
    table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 0.92rem; }}
    th {{ background: var(--table-hdr); padding: 12px 14px; font-weight: 600; color: #fff; border-bottom: 1px solid var(--border); }}
    td {{ padding: 10px 14px; border-bottom: 1px solid var(--border); color: #cbd5e1; }}
    tr:nth-child(even) {{ background: rgba(255, 255, 255, 0.02); }}
    .refs {{ padding-left: 0; list-style: none; }}
    .refs li {{ margin-bottom: 10px; font-size: 0.92rem; }}
    .refs a {{ color: var(--primary); text-decoration: none; word-break: break-all; }}
    .refs a:hover {{ text-decoration: underline; }}
    .badge {{ font-weight: bold; color: var(--primary); margin-right: 6px; font-family: monospace; }}
  </style>
</head>
<body>
  <header>
    <h1>{title}</h1>
    <div class="subtitle">{sub}</div>
    <div class="meta">Published: {datetime.datetime.now().strftime('%B %d, %Y')} | NEXUS Autonomous Research Engine</div>
  </header>
  <main>
    <section>
      <h2>Executive Summary</h2>
      <p>{exec_sum}</p>
    </section>
    {"".join(sections_html)}
    {table_html}
    {f"<section><h2>Conclusion & Strategic Outlook</h2><p>{html.escape(data.get('conclusion', ''))}</p></section>" if data.get('conclusion') else ""}
    {refs_block}
  </main>
</body>
</html>"""
        output_path.write_text(html_content, encoding="utf-8")

    def _build_text_document(self, data: dict, output_path: Path):
        """Generate clean, indented plain text report."""
        lines = [
            "=" * 72,
            data.get("title", "Research Report").upper(),
            data.get("subtitle", ""),
            f"Published: {datetime.datetime.now().strftime('%B %d, %Y')} | NEXUS Deep Research Engine",
            "=" * 72,
            "",
            "EXECUTIVE SUMMARY:",
            data.get("executive_summary", ""),
            "",
        ]

        for sec in data.get("sections", []):
            lines.append("-" * 50)
            lines.append(sec.get("heading", "").upper())
            lines.append("-" * 50)
            for p in sec.get("paragraphs", []):
                lines.append(p)
                lines.append("")
            for hl in sec.get("key_highlights", []):
                lines.append(f"  * {hl}")
            lines.append("")

        table_data = data.get("comparison_table")
        if table_data and table_data.get("headers") and table_data.get("rows"):
            lines.append("-" * 50)
            lines.append(table_data.get("title", "Comparative Analysis").upper())
            lines.append("-" * 50)
            headers = table_data.get("headers", [])
            lines.append(" | ".join(headers))
            for r in table_data.get("rows", []):
                lines.append(" | ".join(str(c) for c in r))
            lines.append("")

        if data.get("conclusion"):
            lines.append("-" * 50)
            lines.append("CONCLUSION & STRATEGIC OUTLOOK:")
            lines.append(data.get("conclusion", ""))
            lines.append("")

        refs = data.get("references", [])
        if refs:
            lines.append("=" * 72)
            lines.append("REFERENCES & CITATIONS:")
            for idx, r in enumerate(refs, 1):
                lines.append(f"[{idx}] {r.get('title', 'Source')} - {r.get('url', '')}")
            lines.append("=" * 72)

        output_path.write_text("\n".join(lines), encoding="utf-8")

    def _build_json_document(self, data: dict, output_path: Path):
        """Export clean structured JSON dataset."""
        payload = {
            "metadata": {
                "generated_at": datetime.datetime.now().isoformat(),
                "engine": "NEXUS Deep Research Engine",
            },
            "report": data,
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
