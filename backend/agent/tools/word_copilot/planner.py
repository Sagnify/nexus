"""Natural language plan compiler for Word Copilot operations.

Parses user prompts into structured tool calls for:
1. Text Formatting (bold, italic, underline, size, color, highlight, font name)
2. Copy, Cut & Paste (copy, cut, paste, duplicate)
3. Find & Replace (search & replace text)
4. Paragraph Formatting (alignment, line spacing, indentation, bullets/numbering)
5. Insert Operations (tables, images, shapes, hyperlinks, headers/footers, page breaks)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nexus.word_copilot.planner")


def build_word_copilot_plan(
    instruction: str,
    active_target: Dict[str, Any],
    context: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """
    Compile user's natural language instruction into a structured 1-step or multi-step Word plan.
    Returns list of plan steps with tool name and args, or None for dynamic LLM fallback.
    """
    clean = instruction.strip()
    lower = clean.lower()

    target_doc = active_target.get("target_name")
    hwnd = active_target.get("window_id")
    try:
        numeric_hwnd = int(hwnd) if hwnd and str(hwnd).isdigit() else None
    except Exception:
        numeric_hwnd = None

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Text Formatting
    # ─────────────────────────────────────────────────────────────────────────
    # Bold
    if any(k in lower for k in ("bold", "unbold")):
        is_bold = not any(k in lower for k in ("unbold", "remove bold", "disable bold", "turn off bold"))
        # Check if there is target text specified: "make 'Hello' bold" or "bold 'Hello'"
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": "Format Text: Bold",
            "description": f"{'Enable' if is_bold else 'Disable'} bold on {'selected text' if not target_text else repr(target_text)}.",
            "tool": "word_format_text",
            "args": {"bold": is_bold, "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Italic
    if any(k in lower for k in ("italic", "italics", "unitalic")):
        is_italic = not any(k in lower for k in ("unitalic", "remove italic", "disable italic"))
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": "Format Text: Italic",
            "description": f"{'Enable' if is_italic else 'Disable'} italic on {'selected text' if not target_text else repr(target_text)}.",
            "tool": "word_format_text",
            "args": {"italic": is_italic, "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Underline
    if any(k in lower for k in ("underline", "underlined", "double underline")):
        is_underline = "double" if "double" in lower else (not any(k in lower for k in ("remove underline", "no underline", "disable underline")))
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": "Format Text: Underline",
            "description": f"Apply underline to {'selected text' if not target_text else repr(target_text)}.",
            "tool": "word_format_text",
            "args": {"underline": is_underline, "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Font Size (e.g. "font size 16", "size 14", "set font to 18", "make font size 24")
    size_match = re.search(r"(?:font\s+)?size\s+(?:to\s+)?(\d{1,2}(?:\.\d)?)", lower)
    if size_match:
        f_size = float(size_match.group(1))
        return [{
            "title": f"Format Text: Font Size {f_size}pt",
            "description": f"Set font size to {f_size}pt.",
            "tool": "word_format_text",
            "args": {"font_size": f_size, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Font Color (e.g. "change color to red", "font color blue", "make text red")
    color_match = re.search(r"(?:font\s+|text\s+)?color\s+(?:to\s+)?([a-z]+|#[0-9a-fA-F]{6})", lower)
    if not color_match:
        color_match = re.search(r"make\s+(?:the\s+)?(?:text\s+)?(red|blue|green|yellow|purple|orange|black|white|dark blue|cyan|gray|navy)", lower)
    if color_match:
        chosen_color = color_match.group(1).strip()
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": f"Format Text: Color {chosen_color.capitalize()}",
            "description": f"Change text color to {chosen_color}.",
            "tool": "word_format_text",
            "args": {"font_color": chosen_color, "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Highlight (e.g. "highlight yellow", "highlight text", "highlight green")
    if "highlight" in lower:
        hl_color = "yellow"
        for c in ("yellow", "green", "cyan", "turquoise", "pink", "magenta", "red", "blue", "none"):
            if c in lower:
                hl_color = c
                break
        return [{
            "title": f"Highlight Text ({hl_color.capitalize()})",
            "description": f"Highlight selection with {hl_color}.",
            "tool": "word_format_text",
            "args": {"highlight_color": hl_color, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Font Name / Family (e.g. "change font to Arial", "font Times New Roman", "set font Calibri")
    font_family_match = re.search(r"(?:change\s+|set\s+)?font(?:\s+family)?\s+(?:to\s+)?([a-zA-Z\s]{3,25})$", clean)
    if font_family_match and not any(k in lower for k in ("size", "color")):
        font_name = font_family_match.group(1).strip()
        return [{
            "title": f"Change Font: {font_name}",
            "description": f"Set font family to {font_name}.",
            "tool": "word_format_text",
            "args": {"font_name": font_name, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Strikethrough
    if "strikethrough" in lower or "strike through" in lower:
        return [{
            "title": "Format Text: Strikethrough",
            "description": "Apply strikethrough to selected text.",
            "tool": "word_format_text",
            "args": {"strikethrough": True, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Case conversion (uppercase, lowercase, title case)
    if any(k in lower for k in ("uppercase", "capital letters", "all caps")):
        return [{
            "title": "Convert Case: UPPERCASE",
            "description": "Convert selected text to uppercase.",
            "tool": "word_format_text",
            "args": {"case": "uppercase", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("lowercase", "small letters")):
        return [{
            "title": "Convert Case: lowercase",
            "description": "Convert selected text to lowercase.",
            "tool": "word_format_text",
            "args": {"case": "lowercase", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("title case", "capitalize words")):
        return [{
            "title": "Convert Case: Title Case",
            "description": "Convert selected text to Title Case.",
            "tool": "word_format_text",
            "args": {"case": "titlecase", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # ─────────────────────────────────────────────────────────────────────────
    # 2. Copy, Cut & Paste
    # ─────────────────────────────────────────────────────────────────────────
    if lower in ("copy", "copy this", "copy text", "copy selection") or lower.startswith("copy "):
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": "Copy Content",
            "description": f"Copy {'selection' if not target_text else repr(target_text)} to clipboard.",
            "tool": "word_clipboard_op",
            "args": {"operation": "copy", "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    if lower in ("cut", "cut this", "cut text", "cut selection") or lower.startswith("cut "):
        target_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            target_text = q_match.group(1)
        return [{
            "title": "Cut Content",
            "description": f"Cut {'selection' if not target_text else repr(target_text)} to clipboard.",
            "tool": "word_clipboard_op",
            "args": {"operation": "cut", "target_text": target_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    if lower in ("paste", "paste here", "paste text") or lower.startswith("paste "):
        paste_text = None
        q_match = re.search(r"['\"]([^'\"]+)['\"]", clean)
        if q_match:
            paste_text = q_match.group(1)
        return [{
            "title": "Paste Content",
            "description": "Paste content into Word document.",
            "tool": "word_clipboard_op",
            "args": {"operation": "paste", "paste_text": paste_text, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    if any(k in lower for k in ("duplicate", "duplicate paragraph", "duplicate line")):
        return [{
            "title": "Duplicate Content",
            "description": "Duplicate selected paragraph or text.",
            "tool": "word_clipboard_op",
            "args": {"operation": "duplicate", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # ─────────────────────────────────────────────────────────────────────────
    # 3. Find & Replace
    # ─────────────────────────────────────────────────────────────────────────
    # "replace 'X' with 'Y'", "replace X with Y", "change 'X' to 'Y'", "find 'X' and replace with 'Y'"
    rep_match = re.search(
        r"(?:find\s+['\"]?([^'\"]+?)['\"]?\s+and\s+)?replace\s+(?:all\s+)?(?:occurrences\s+of\s+|instances\s+of\s+)?['\"]?([^'\"]+?)['\"]?\s+with\s+['\"]?([^'\"]+?)['\"]?(?:\s+(?:everywhere|in document|across document))?$",
        clean,
        re.IGNORECASE,
    )
    if not rep_match:
        rep_match = re.search(
            r"change\s+(?:all\s+)?(?:occurrences\s+of\s+|instances\s+of\s+)?['\"]?([^'\"]+?)['\"]?\s+to\s+['\"]?([^'\"]+?)['\"]?(?:\s+(?:everywhere|in document))?$",
            clean,
            re.IGNORECASE,
        )

    if rep_match:
        if rep_match.group(1) and "replace" in clean.lower() and "and" in clean.lower():
            find_str = rep_match.group(1).strip()
            repl_str = rep_match.group(3).strip()
        else:
            find_str = rep_match.group(2).strip()
            repl_str = rep_match.group(3).strip()

        return [{
            "title": f"Find & Replace: '{find_str}' → '{repl_str}'",
            "description": f"Replace all occurrences of '{find_str}' with '{repl_str}' in document.",
            "tool": "word_find_replace",
            "args": {
                "find_text": find_str,
                "replace_with": repl_str,
                "replace_all": True,
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Paragraph Formatting
    # ─────────────────────────────────────────────────────────────────────────
    # Alignment (center, left, right, justify)
    if any(k in lower for k in ("center align", "align center", "center paragraph", "center text", "align to center")):
        return [{
            "title": "Align Paragraph: Center",
            "description": "Center align the current paragraph or selection.",
            "tool": "word_format_paragraph",
            "args": {"alignment": "center", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("left align", "align left", "align to left")):
        return [{
            "title": "Align Paragraph: Left",
            "description": "Left align the current paragraph or selection.",
            "tool": "word_format_paragraph",
            "args": {"alignment": "left", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("right align", "align right", "align to right")):
        return [{
            "title": "Align Paragraph: Right",
            "description": "Right align the current paragraph or selection.",
            "tool": "word_format_paragraph",
            "args": {"alignment": "right", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("justify", "justified", "align justify")):
        return [{
            "title": "Align Paragraph: Justify",
            "description": "Justify align paragraph across both margins.",
            "tool": "word_format_paragraph",
            "args": {"alignment": "justify", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Line spacing (1.0, 1.15, 1.5, 2.0 / double space)
    spacing_match = re.search(r"(?:line\s+spacing\s+(?:to\s+|of\s+)?|spacing\s+(?:to\s+|of\s+)?)(\d+(?:\.\d+)?)", lower)
    if spacing_match:
        val = float(spacing_match.group(1))
        return [{
            "title": f"Line Spacing: {val}",
            "description": f"Set paragraph line spacing to {val}.",
            "tool": "word_format_paragraph",
            "args": {"line_spacing": val, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("double space", "double spacing", "2.0 spacing", "line spacing 2")):
        return [{
            "title": "Line Spacing: 2.0 (Double)",
            "description": "Set paragraph line spacing to 2.0 (double).",
            "tool": "word_format_paragraph",
            "args": {"line_spacing": 2.0, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("1.5 spacing", "1.5 line spacing", "line spacing 1.5")):
        return [{
            "title": "Line Spacing: 1.5",
            "description": "Set paragraph line spacing to 1.5.",
            "tool": "word_format_paragraph",
            "args": {"line_spacing": 1.5, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("single space", "single spacing", "1.0 spacing", "line spacing 1")):
        return [{
            "title": "Line Spacing: 1.0 (Single)",
            "description": "Set paragraph line spacing to 1.0 (single).",
            "tool": "word_format_paragraph",
            "args": {"line_spacing": 1.0, "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Indentation (increase indent, decrease indent)
    if any(k in lower for k in ("increase indent", "indent paragraph", "indent right")):
        return [{
            "title": "Indent: Increase (+0.5 in)",
            "description": "Increase left indent by 0.5 inches.",
            "tool": "word_format_paragraph",
            "args": {"indent": "increase", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("decrease indent", "outdent", "remove indent")):
        return [{
            "title": "Indent: Decrease (-0.5 in)",
            "description": "Decrease left indent by 0.5 inches.",
            "tool": "word_format_paragraph",
            "args": {"indent": "decrease", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # Bullets & Numbering
    if any(k in lower for k in ("bullet", "bullets", "bullet points", "bulleted list")):
        is_remove = any(k in lower for k in ("remove bullet", "no bullet", "remove list"))
        return [{
            "title": "List: Bullet Points",
            "description": f"{'Remove' if is_remove else 'Apply'} bullet points list.",
            "tool": "word_format_paragraph",
            "args": {"bullets": "none" if is_remove else "bullet", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]
    if any(k in lower for k in ("numbering", "numbered list", "number list")):
        is_remove = any(k in lower for k in ("remove number", "no number"))
        return [{
            "title": "List: Numbered List",
            "description": f"{'Remove' if is_remove else 'Apply'} numbered list.",
            "tool": "word_format_paragraph",
            "args": {"bullets": "none" if is_remove else "number", "hwnd": numeric_hwnd, "document_name": target_doc},
        }]

    # ─────────────────────────────────────────────────────────────────────────
    # 5. Insert Operations
    # ─────────────────────────────────────────────────────────────────────────
    # Insert Table: "insert table 3x4", "add table 4 rows 3 columns", "create a table with columns Name, Age, Email"
    if "table" in lower and any(k in lower for k in ("insert", "add", "create", "make")):
        r_num, c_num = 3, 3
        # Match dimensions like 3x4 or 3 by 4
        dim_match = re.search(r"(\d+)\s*(?:x|by|\*)\s*(\d+)", lower)
        if dim_match:
            r_num = int(dim_match.group(1))
            c_num = int(dim_match.group(2))
        else:
            r_m = re.search(r"(\d+)\s+rows?", lower)
            c_m = re.search(r"(\d+)\s+col(?:umn)?s?", lower)
            if r_m: r_num = int(r_m.group(1))
            if c_m: c_num = int(c_m.group(1))

        # Check for column header list: "columns Name, Age, Email"
        headers_list = None
        hdr_match = re.search(r"(?:columns?|headers?|fields?)\s+(?:named\s+|called\s+|with\s+)?([a-zA-Z0-9_,\s\-]+)", clean, re.IGNORECASE)
        if hdr_match:
            raw_h = hdr_match.group(1).split(",")
            headers_list = [h.strip() for h in raw_h if h.strip()]
            if headers_list and len(headers_list) > c_num:
                c_num = len(headers_list)

        return [{
            "title": f"Insert Table ({r_num}x{c_num})",
            "description": f"Insert a {r_num}x{c_num} table into document.",
            "tool": "word_insert",
            "args": {
                "item_type": "table",
                "rows": r_num,
                "cols": c_num,
                "headers": headers_list,
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    # Insert Image: "insert image ...", "add picture ..."
    if any(k in lower for k in ("insert image", "add image", "insert picture", "add picture", "insert photo")):
        path_match = re.search(r"['\"]([^'\"]+\.(?:png|jpg|jpeg|gif|bmp))['\"]", clean, re.IGNORECASE)
        if not path_match:
            path_match = re.search(r"(https?://\S+)", clean)
        if not path_match:
            path_match = re.search(r"(?:from|at|path)\s+([a-zA-Z0-9_\-\\\/\.]+\.(?:png|jpg|jpeg|gif))", clean, re.IGNORECASE)

        img_path = path_match.group(1) if path_match else None
        if img_path:
            return [{
                "title": f"Insert Image: {img_path}",
                "description": f"Insert image from {img_path} into Word document.",
                "tool": "word_insert",
                "args": {
                    "item_type": "image",
                    "path_or_url": img_path,
                    "hwnd": numeric_hwnd,
                    "document_name": target_doc,
                },
            }]

    # Insert Shape: "insert shape rectangle", "add rectangle shape", "insert arrow"
    if any(k in lower for k in ("shape", "rectangle", "oval", "circle", "arrow", "star")):
        shape_type = "rectangle"
        for s in ("rectangle", "rounded_rectangle", "oval", "circle", "arrow", "star", "heart"):
            if s in lower:
                shape_type = "rounded_rectangle" if "rounded" in lower else s
                break
        return [{
            "title": f"Insert Shape: {shape_type.capitalize()}",
            "description": f"Insert a {shape_type} shape into Word document.",
            "tool": "word_insert",
            "args": {
                "item_type": "shape",
                "shape_type": shape_type,
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    # Insert Hyperlink: "insert link ...", "add hyperlink to https://..."
    if any(k in lower for k in ("hyperlink", "link")) and any(k in lower for k in ("insert", "add", "create")):
        url_match = re.search(r"(https?://[^\s'\"]+)", clean)
        text_match = re.search(r"(?:text|title|label)\s+['\"]?([^'\"]+?)['\"]?(?:\s|$)", clean)
        if url_match:
            url_str = url_match.group(1).strip()
            disp_text = text_match.group(1).strip() if text_match else url_str
            return [{
                "title": f"Insert Hyperlink: {disp_text}",
                "description": f"Insert hyperlink to {url_str}.",
                "tool": "word_insert",
                "args": {
                    "item_type": "hyperlink",
                    "url": url_str,
                    "text": disp_text,
                    "hwnd": numeric_hwnd,
                    "document_name": target_doc,
                },
            }]

    # Insert Header / Footer: "add header 'Company Report'", "insert footer Page 1"
    if "header" in lower and any(k in lower for k in ("insert", "add", "create", "set")):
        text_match = re.search(r"(?:header\s+)?['\"]([^'\"]+)['\"]", clean)
        hdr_text = text_match.group(1) if text_match else clean.replace("insert header", "").replace("add header", "").strip()
        include_page = "page" in lower
        return [{
            "title": "Insert Header",
            "description": f"Set document header to '{hdr_text}'.",
            "tool": "word_insert",
            "args": {
                "item_type": "header",
                "text": hdr_text,
                "include_page_number": include_page,
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    if "footer" in lower and any(k in lower for k in ("insert", "add", "create", "set")):
        text_match = re.search(r"(?:footer\s+)?['\"]([^'\"]+)['\"]", clean)
        ftr_text = text_match.group(1) if text_match else clean.replace("insert footer", "").replace("add footer", "").strip()
        include_page = "page" in lower
        return [{
            "title": "Insert Footer",
            "description": f"Set document footer to '{ftr_text}'.",
            "tool": "word_insert",
            "args": {
                "item_type": "footer",
                "text": ftr_text,
                "include_page_number": include_page,
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    # Page Break: "insert page break", "new page"
    if any(k in lower for k in ("page break", "new page", "insert break")):
        return [{
            "title": "Insert Page Break",
            "description": "Insert page break into document.",
            "tool": "word_insert",
            "args": {
                "item_type": "page_break",
                "hwnd": numeric_hwnd,
                "document_name": target_doc,
            },
        }]

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Presentation / PowerPoint Generation from Context
    # ─────────────────────────────────────────────────────────────────────────
    # e.g. "make a powerpoint presentation on that context or topic and save it in desktop"
    # "take the context from the word file and make a powerpoint presentation on that context or topic and save it in desktop"
    # "create a presentation from this document on desktop", "make ppt", "generate presentation"
    if any(k in lower for k in ("powerpoint", "presentation", "slides", "slide deck", "ppt", "pptx")):
        if any(k in lower for k in ("make", "create", "generate", "build", "convert", "topic", "context", "desktop", "export", "take")):
            extracted_topic = None
            topic_match = re.search(
                r"\b(?:on|about|topic)\s+['\"]?(.+?)['\"]?(?:\s+(?:and\s+save|and\s+put|and\s+store|save\s+to|saved\s+to|in\s+desktop|to\s+desktop|on\s+desktop|$))",
                clean,
                re.IGNORECASE,
            )
            if topic_match:
                candidate = topic_match.group(1).strip()
                ignored_terms = (
                    "that context", "that topic", "this context", "this topic", "context", "topic",
                    "that context or topic", "this context or topic", "context or topic",
                    "word", "word file", "word document", "document", "desktop", "file", "it",
                )
                if candidate.lower() not in ignored_terms:
                    extracted_topic = candidate

            slides_match = re.search(r"(\d+)\s*slides?", lower)
            num_slides = int(slides_match.group(1)) if slides_match else 6

            theme = "executive_navy"
            for t_candidate in ("modern_dark", "tech_indigo", "emerald_green", "corporate_light"):
                if t_candidate.replace("_", " ") in lower or t_candidate in lower:
                    theme = t_candidate
                    break

            dest = "Desktop"
            if "downloads" in lower:
                dest = "Downloads"
            elif "documents" in lower:
                dest = "Documents"

            return [{
                "title": "Create PowerPoint Presentation on Desktop",
                "description": f"Extract context from active Word document and generate a {num_slides}-slide PowerPoint presentation saved to {dest}.",
                "tool": "word_create_presentation",
                "args": {
                    "topic": extracted_topic,
                    "num_slides": num_slides,
                    "theme": theme,
                    "output_path": dest,
                    "hwnd": numeric_hwnd,
                    "document_name": target_doc,
                },
            }]

    return None
