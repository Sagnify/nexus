"""Rich Microsoft Word context acquisition engine.

Extracts deep structural knowledge of the targeted Word document:
document properties, active selection text, current paragraph styling,
font properties, tables, word/paragraph counts, and headings outline.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from backend.agent.tools.word_copilot.resolver import resolve_word_target

logger = logging.getLogger("nexus.word_copilot.context")


def acquire_deep_word_context(
    document_name: Optional[str] = None,
    hwnd: Optional[int] = None,
    target_dict: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Acquire comprehensive, real-time context for the targeted Word document.
    Used by the floating pill and planner to interpret natural-language commands without guesswork.
    """
    word_app, doc, win = resolve_word_target(
        document_name=document_name,
        hwnd=hwnd,
        target_dict=target_dict,
    )

    doc_name = str(getattr(doc, "Name", "Document1"))
    doc_path = str(getattr(doc, "FullName", doc_name))
    is_saved = bool(getattr(doc, "Saved", False))

    context: Dict[str, Any] = {
        "application": "Microsoft Word",
        "version": str(getattr(word_app, "Version", "")),
        "document_name": doc_name,
        "document_path": doc_path,
        "is_saved": is_saved,
        "selection": {
            "text": "",
            "length": 0,
            "has_selection": False,
            "start": 0,
            "end": 0,
        },
        "active_style": {
            "font_name": "Calibri",
            "font_size": 11.0,
            "bold": False,
            "italic": False,
            "underline": False,
            "alignment": "left",
            "paragraph_text": "",
        },
        "statistics": {
            "words": 0,
            "paragraphs": 0,
            "characters": 0,
            "tables": 0,
            "shapes": 0,
            "hyperlinks": 0,
        },
        "headings": [],
    }

    # 1. Inspect Document Statistics
    try:
        context["statistics"]["words"] = int(doc.Words.Count)
        context["statistics"]["paragraphs"] = int(doc.Paragraphs.Count)
        context["statistics"]["characters"] = int(doc.Characters.Count)
        context["statistics"]["tables"] = int(doc.Tables.Count)
        context["statistics"]["shapes"] = int(doc.Shapes.Count + getattr(doc, "InlineShapes", []).Count if hasattr(doc, "InlineShapes") else doc.Shapes.Count)
        context["statistics"]["hyperlinks"] = int(doc.Hyperlinks.Count)
    except Exception as stat_err:
        logger.debug(f"Error reading Word document stats: {stat_err}")

    # 2. Inspect Active Selection & Active Paragraph
    try:
        sel = getattr(word_app, "Selection", None)
        if sel:
            sel_text = str(sel.Text or "")
            # Word puts \r at end of selection text; clean it for display
            clean_sel = sel_text.replace("\r", " ").strip()
            context["selection"]["text"] = clean_sel[:500]
            context["selection"]["length"] = len(clean_sel)
            context["selection"]["has_selection"] = len(clean_sel) > 0
            context["selection"]["start"] = int(getattr(sel, "Start", 0))
            context["selection"]["end"] = int(getattr(sel, "End", 0))

            # Active paragraph text
            try:
                para = sel.Paragraphs(1) if sel.Paragraphs.Count > 0 else None
                if para:
                    para_text = str(para.Range.Text or "").replace("\r", " ").strip()
                    context["active_style"]["paragraph_text"] = para_text[:300]
            except Exception:
                pass

            # Active font formatting
            try:
                font = sel.Font
                if font:
                    context["active_style"]["font_name"] = str(getattr(font, "Name", "Calibri"))
                    context["active_style"]["font_size"] = float(getattr(font, "Size", 11.0))
                    context["active_style"]["bold"] = bool(getattr(font, "Bold", 0) in (-1, 1, True))
                    context["active_style"]["italic"] = bool(getattr(font, "Italic", 0) in (-1, 1, True))
                    context["active_style"]["underline"] = bool(getattr(font, "Underline", 0) not in (0, False))
            except Exception:
                pass

            # Active paragraph alignment
            try:
                pf = sel.ParagraphFormat
                if pf:
                    align_val = getattr(pf, "Alignment", 0)
                    align_map = {0: "left", 1: "center", 2: "right", 3: "justify"}
                    context["active_style"]["alignment"] = align_map.get(align_val, "left")
            except Exception:
                pass
    except Exception as sel_err:
        logger.debug(f"Error reading Word selection: {sel_err}")

    # 3. Extract outline / headings preview (first 10 headings)
    try:
        headings = []
        for p in doc.Paragraphs:
            try:
                style_name = str(p.Style.NameLocal or "")
                if "heading" in style_name.lower():
                    t = str(p.Range.Text or "").replace("\r", "").strip()
                    if t:
                        headings.append({"style": style_name, "text": t[:80]})
                        if len(headings) >= 10:
                            break
            except Exception:
                pass
        context["headings"] = headings
    except Exception as head_err:
        logger.debug(f"Error reading Word headings: {head_err}")

    return context
