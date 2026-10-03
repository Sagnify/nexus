"""Live Microsoft Word Copilot Execution Tools.

Implements native COM actions on active Word documents across the 5 core categories:
1. Text Formatting (Bold, Italic, Underline, Font Size, Font Color, Highlight)
2. Copy, Cut & Paste (Copy, Cut, Paste, Duplicate)
3. Find & Replace (Search & Replace text across document)
4. Paragraph Formatting (Alignment, Line Spacing, Indentation, Bullets & Numbering)
5. Insert Operations (Tables, Images, Shapes, Hyperlinks, Headers/Footers, Page Breaks)
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple, Union

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.word_copilot.resolver import resolve_word_target, WordTargetError
from backend.agent.tools.presentation.adapter import presentation_adapter

logger = logging.getLogger("nexus.word_copilot.tools")

# WdConstants
WD_ALIGN_LEFT = 0
WD_ALIGN_CENTER = 1
WD_ALIGN_RIGHT = 2
WD_ALIGN_JUSTIFY = 3

WD_UNDERLINE_NONE = 0
WD_UNDERLINE_SINGLE = 1
WD_UNDERLINE_DOUBLE = 2

WD_REPLACE_NONE = 0
WD_REPLACE_ONE = 1
WD_REPLACE_ALL = 2

WD_PAGE_BREAK = 7
WD_HEADER_PRIMARY = 1
WD_FOOTER_PRIMARY = 1

# Color map to COM RGB integer: r + (g * 256) + (b * 65536)
COLOR_MAP = {
    "black": 0,
    "white": 16777215,
    "red": 255,
    "green": 32768,
    "blue": 16711680,
    "dark blue": 8388608,
    "navy": 8388608,
    "yellow": 65535,
    "orange": 33023,
    "purple": 8388736,
    "magenta": 16711935,
    "cyan": 16776960,
    "gray": 8421504,
    "grey": 8421504,
    "dark gray": 4210752,
    "light gray": 12632256,
}

# WdColorIndex for Highlights
HIGHLIGHT_MAP = {
    "yellow": 7,      # wdYellow
    "green": 4,       # wdBrightGreen
    "blue": 2,        # wdBlue
    "cyan": 3,        # wdTurquoise
    "turquoise": 3,
    "pink": 5,        # wdPink
    "magenta": 5,
    "red": 6,         # wdRed
    "dark blue": 9,   # wdDarkBlue
    "teal": 10,       # wdTeal
    "violet": 12,     # wdViolet
    "dark red": 13,   # wdDarkRed
    "gray": 15,       # wdGray50
    "light gray": 16, # wdGray25
    "none": 0,        # wdNoHighlight
}


def _parse_color(val: Union[str, int]) -> Optional[int]:
    """Parse color string or hex into Windows BGR integer."""
    if isinstance(val, int):
        return val
    s = str(val).strip().lower()
    if s in COLOR_MAP:
        return COLOR_MAP[s]
    # Check hex #RRGGBB
    if s.startswith("#") and len(s) == 7:
        try:
            r = int(s[1:3], 16)
            g = int(s[3:5], 16)
            b = int(s[5:7], 16)
            return r + (g * 256) + (b * 65536)
        except Exception:
            pass
    return None


def _get_target_range(word_app: Any, doc: Any, target_text: Optional[str] = None) -> Any:
    """Return target range: specific text if matched, active selection if non-empty, or current paragraph."""
    sel = getattr(word_app, "Selection", None)
    if target_text:
        # Search for target text in document
        find_rng = doc.Content
        find = find_rng.Find
        find.ClearFormatting()
        if find.Execute(FindText=target_text):
            return find_rng

    if sel and hasattr(sel, "Range") and (sel.End - sel.Start > 0):
        return sel.Range

    if sel and hasattr(sel, "Paragraphs") and sel.Paragraphs.Count > 0:
        return sel.Paragraphs(1).Range

    return doc.Content


# ─────────────────────────────────────────────────────────────────────────────
# 1. Text Formatting Tool
# ─────────────────────────────────────────────────────────────────────────────
class WordFormatTextTool(NexusTool):
    name = "word_format_text"
    description = (
        "Format text in active Word document: bold, italic, underline, font size, "
        "font color, font name, highlight color, strikethrough, or case conversion."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[Union[bool, str]] = None,
        font_size: Optional[Union[float, int]] = None,
        font_name: Optional[str] = None,
        font_color: Optional[str] = None,
        highlight_color: Optional[str] = None,
        strikethrough: Optional[bool] = None,
        case: Optional[str] = None,  # "uppercase", "lowercase", "titlecase"
        target_text: Optional[str] = None,
        hwnd: Optional[int] = None,
        document_name: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(document_name=document_name, hwnd=hwnd)
            sel = getattr(word_app, "Selection", None)
            rng = _get_target_range(word_app, doc, target_text)

            applied_actions = []

            # Bold
            if bold is not None:
                rng.Font.Bold = -1 if bold else 0
                applied_actions.append(f"Bold: {'enabled' if bold else 'disabled'}")

            # Italic
            if italic is not None:
                rng.Font.Italic = -1 if italic else 0
                applied_actions.append(f"Italic: {'enabled' if italic else 'disabled'}")

            # Underline
            if underline is not None:
                if underline is True or str(underline).lower() in ("single", "true", "yes"):
                    rng.Font.Underline = WD_UNDERLINE_SINGLE
                    applied_actions.append("Underline: single")
                elif str(underline).lower() in ("double",):
                    rng.Font.Underline = WD_UNDERLINE_DOUBLE
                    applied_actions.append("Underline: double")
                else:
                    rng.Font.Underline = WD_UNDERLINE_NONE
                    applied_actions.append("Underline: none")

            # Font Size
            if font_size is not None:
                try:
                    f_size = float(font_size)
                    rng.Font.Size = f_size
                    applied_actions.append(f"Font Size: {f_size}pt")
                except Exception:
                    pass

            # Font Name
            if font_name:
                rng.Font.Name = str(font_name).strip()
                applied_actions.append(f"Font Family: {font_name}")

            # Font Color
            if font_color:
                rgb_val = _parse_color(font_color)
                if rgb_val is not None:
                    rng.Font.Color = rgb_val
                    applied_actions.append(f"Font Color: {font_color}")

            # Highlight Color
            if highlight_color:
                hl_key = str(highlight_color).strip().lower()
                hl_val = HIGHLIGHT_MAP.get(hl_key)
                if hl_val is not None:
                    rng.HighlightColorIndex = hl_val
                    applied_actions.append(f"Highlight: {highlight_color}")

            # Strikethrough
            if strikethrough is not None:
                rng.Font.StrikeThrough = -1 if strikethrough else 0
                applied_actions.append(f"Strikethrough: {'enabled' if strikethrough else 'disabled'}")

            # Case Conversion
            if case:
                c_lower = str(case).lower()
                text_content = str(rng.Text or "")
                if c_lower in ("upper", "uppercase"):
                    rng.Text = text_content.upper()
                    applied_actions.append("Case: UPPERCASE")
                elif c_lower in ("lower", "lowercase"):
                    rng.Text = text_content.lower()
                    applied_actions.append("Case: lowercase")
                elif c_lower in ("title", "titlecase"):
                    rng.Text = text_content.title()
                    applied_actions.append("Case: Title Case")

            msg = f"Applied text formatting to {doc.Name}: {', '.join(applied_actions) if applied_actions else 'No changes'}"
            return ToolResult(
                success=True,
                output=msg,
                metadata={
                    "document": str(doc.Name),
                    "applied": applied_actions,
                    "target_text": target_text,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Text formatting failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Copy, Cut & Paste Tool
# ─────────────────────────────────────────────────────────────────────────────
class WordClipboardOpTool(NexusTool):
    name = "word_clipboard_op"
    description = (
        "Perform clipboard operations in Word: copy, cut, paste, or duplicate selected text/content."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        operation: str,  # "copy", "cut", "paste", "duplicate"
        target_text: Optional[str] = None,
        paste_text: Optional[str] = None,
        position: Optional[str] = None,  # "selection", "end", "start"
        hwnd: Optional[int] = None,
        document_name: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(document_name=document_name, hwnd=hwnd)
            sel = getattr(word_app, "Selection", None)
            if not sel:
                return ToolResult(success=False, error="No active selection available in Word.")

            op = str(operation).strip().lower()

            # Locate specific target text first if requested
            if target_text:
                find = doc.Content.Find
                find.ClearFormatting()
                if find.Execute(FindText=target_text):
                    sel.SetRange(find.Parent.Start, find.Parent.End)

            # Move selection to desired position if requested
            if position == "end":
                sel.EndKey(Unit=6)  # wdStory = 6
            elif position == "start":
                sel.HomeKey(Unit=6)

            if op == "copy":
                sel.Copy()
                return ToolResult(
                    success=True,
                    output=f"Copied selection to clipboard ({len(sel.Text or '')} chars).",
                    metadata={"operation": "copy"},
                )

            elif op == "cut":
                cut_len = len(sel.Text or "")
                sel.Cut()
                return ToolResult(
                    success=True,
                    output=f"Cut selection to clipboard ({cut_len} chars).",
                    metadata={"operation": "cut"},
                )

            elif op == "paste":
                if paste_text:
                    sel.TypeText(paste_text)
                    return ToolResult(
                        success=True,
                        output=f"Inserted text into document: '{paste_text[:50]}...'",
                        metadata={"operation": "paste_text"},
                    )
                else:
                    sel.Paste()
                    return ToolResult(
                        success=True,
                        output="Pasted clipboard contents into Word document.",
                        metadata={"operation": "paste"},
                    )

            elif op == "duplicate":
                # Copy current selection or paragraph and paste immediately after
                rng = sel.Range if (sel.End - sel.Start > 0) else sel.Paragraphs(1).Range
                copied_text = str(rng.Text or "")
                rng.Copy()
                rng.Collapse(0)  # wdCollapseEnd = 0
                rng.Paste()
                return ToolResult(
                    success=True,
                    output=f"Duplicated content successfully: '{copied_text[:40]}...'",
                    metadata={"operation": "duplicate"},
                )

            else:
                return ToolResult(success=False, error=f"Unknown clipboard operation: '{operation}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Clipboard operation failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 3. Find & Replace Tool
# ─────────────────────────────────────────────────────────────────────────────
class WordFindReplaceTool(NexusTool):
    name = "word_find_replace"
    description = (
        "Find and replace text throughout the active Microsoft Word document."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        find_text: str,
        replace_with: str,
        replace_all: bool = True,
        match_case: bool = False,
        whole_word: bool = False,
        hwnd: Optional[int] = None,
        document_name: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(document_name=document_name, hwnd=hwnd)

            if not find_text:
                return ToolResult(success=False, error="find_text cannot be empty.")

            find_obj = doc.Content.Find
            find_obj.ClearFormatting()
            find_obj.Replacement.ClearFormatting()

            replace_mode = WD_REPLACE_ALL if replace_all else WD_REPLACE_ONE

            res = find_obj.Execute(
                FindText=find_text,
                MatchCase=bool(match_case),
                MatchWholeWord=bool(whole_word),
                ReplaceWith=replace_with,
                Replace=replace_mode,
            )

            msg = f"Replaced occurrences of '{find_text}' with '{replace_with}' in {doc.Name}."
            return ToolResult(
                success=True,
                output=msg,
                metadata={
                    "document": str(doc.Name),
                    "find_text": find_text,
                    "replace_with": replace_with,
                    "replace_all": replace_all,
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Find and replace failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 4. Paragraph Formatting Tool
# ─────────────────────────────────────────────────────────────────────────────
class WordFormatParagraphTool(NexusTool):
    name = "word_format_paragraph"
    description = (
        "Format paragraphs in Word: alignment (left, center, right, justify), "
        "line spacing (1.0, 1.15, 1.5, 2.0), indentation, bullets, numbering, or paragraph spacing."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        alignment: Optional[str] = None,  # "left", "center", "right", "justify"
        line_spacing: Optional[float] = None,  # 1.0, 1.15, 1.5, 2.0
        indent: Optional[Union[str, float]] = None,  # "increase", "decrease", or points
        bullets: Optional[Union[str, bool]] = None,  # "bullet", "number", "none", True, False
        space_before: Optional[float] = None,  # points
        space_after: Optional[float] = None,  # points
        target_text: Optional[str] = None,
        hwnd: Optional[int] = None,
        document_name: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(document_name=document_name, hwnd=hwnd)
            sel = getattr(word_app, "Selection", None)
            rng = _get_target_range(word_app, doc, target_text)
            pf = rng.ParagraphFormat

            applied = []

            # Alignment
            if alignment:
                a_str = str(alignment).strip().lower()
                if a_str == "center":
                    pf.Alignment = WD_ALIGN_CENTER
                    applied.append("Alignment: Center")
                elif a_str == "right":
                    pf.Alignment = WD_ALIGN_RIGHT
                    applied.append("Alignment: Right")
                elif a_str == "justify":
                    pf.Alignment = WD_ALIGN_JUSTIFY
                    applied.append("Alignment: Justify")
                elif a_str == "left":
                    pf.Alignment = WD_ALIGN_LEFT
                    applied.append("Alignment: Left")

            # Line Spacing
            if line_spacing is not None:
                try:
                    ls = float(line_spacing)
                    if ls == 1.0:
                        pf.LineSpacingRule = 0  # wdLineSpaceSingle
                        applied.append("Line Spacing: 1.0 (Single)")
                    elif ls == 1.5:
                        pf.LineSpacingRule = 1  # wdLineSpace1pt5
                        applied.append("Line Spacing: 1.5")
                    elif ls == 2.0:
                        pf.LineSpacingRule = 2  # wdLineSpaceDouble
                        applied.append("Line Spacing: 2.0 (Double)")
                    else:
                        pf.LineSpacing = ls * 12  # in points
                        applied.append(f"Line Spacing: {ls}")
                except Exception:
                    pass

            # Indentation
            if indent is not None:
                if str(indent).lower() in ("increase", "indent", "in"):
                    pf.LeftIndent += 36  # 0.5 inch (36 points)
                    applied.append("Left Indent: Increased (+0.5 in)")
                elif str(indent).lower() in ("decrease", "outdent", "out"):
                    pf.LeftIndent = max(0, pf.LeftIndent - 36)
                    applied.append("Left Indent: Decreased (-0.5 in)")
                else:
                    try:
                        pts = float(indent)
                        pf.LeftIndent = pts
                        applied.append(f"Left Indent: {pts}pt")
                    except Exception:
                        pass

            # Bullets & Numbering
            if bullets is not None:
                b_str = str(bullets).strip().lower()
                if b_str in ("bullet", "bullets", "true", "yes"):
                    rng.ListFormat.ApplyBulletDefault()
                    applied.append("List: Bullets enabled")
                elif b_str in ("number", "numbered", "numbering", "numbers"):
                    rng.ListFormat.ApplyNumberDefault()
                    applied.append("List: Numbering enabled")
                elif b_str in ("none", "false", "no", "remove"):
                    rng.ListFormat.RemoveNumbers()
                    applied.append("List: Removed")

            # Paragraph Spacing
            if space_before is not None:
                pf.SpaceBefore = float(space_before)
                applied.append(f"Space Before: {space_before}pt")
            if space_after is not None:
                pf.SpaceAfter = float(space_after)
                applied.append(f"Space After: {space_after}pt")

            msg = f"Applied paragraph formatting: {', '.join(applied) if applied else 'No changes'}"
            return ToolResult(
                success=True,
                output=msg,
                metadata={"document": str(doc.Name), "applied": applied},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Paragraph formatting failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# 5. Insert Operations Tool
# ─────────────────────────────────────────────────────────────────────────────
class WordInsertTool(NexusTool):
    name = "word_insert"
    description = (
        "Insert elements into active Word document: tables, images, shapes, "
        "hyperlinks, headers, footers, or page breaks."
    )
    risk_level = RiskLevel.SAFE

    async def execute(
        self,
        item_type: str,  # "table", "image", "shape", "hyperlink", "header", "footer", "page_break"
        # Table arguments
        rows: int = 3,
        cols: int = 3,
        headers: Optional[List[str]] = None,
        data: Optional[List[List[str]]] = None,
        # Image arguments
        path_or_url: Optional[str] = None,
        # Shape arguments
        shape_type: str = "rectangle",  # "rectangle", "oval", "arrow", "rounded_rectangle"
        shape_text: Optional[str] = None,
        # Hyperlink arguments
        url: Optional[str] = None,
        text: Optional[str] = None,
        # Header/Footer arguments
        include_page_number: bool = False,
        hwnd: Optional[int] = None,
        document_name: Optional[str] = None,
        **_: Any,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(document_name=document_name, hwnd=hwnd)
            sel = getattr(word_app, "Selection", None)
            if not sel:
                return ToolResult(success=False, error="No active selection in Word.")

            t_type = str(item_type).strip().lower()

            # ── 1. Insert Table ──
            if t_type in ("table", "grid"):
                r_count = max(1, int(rows))
                c_count = max(1, int(cols))

                if headers and len(headers) > c_count:
                    c_count = len(headers)
                if data and len(data) > 0:
                    r_count = max(r_count, len(data) + (1 if headers else 0))

                tbl = doc.Tables.Add(Range=sel.Range, NumRows=r_count, NumColumns=c_count)
                try:
                    tbl.Borders.Enable = True
                except Exception:
                    pass

                # Populate headers
                if headers:
                    for i, h_text in enumerate(headers[:c_count]):
                        cell_rng = tbl.Cell(1, i + 1).Range
                        cell_rng.Text = str(h_text)
                        cell_rng.Font.Bold = True
                        try:
                            cell_rng.Shading.BackgroundPatternColor = 15132390  # Light grayish blue
                        except Exception:
                            pass

                # Populate data rows
                if data:
                    start_row = 2 if headers else 1
                    for r_idx, row_values in enumerate(data):
                        target_r = start_row + r_idx
                        if target_r > r_count:
                            break
                        for c_idx, val in enumerate(row_values[:c_count]):
                            tbl.Cell(target_r, c_idx + 1).Range.Text = str(val)

                # Move cursor after table
                sel.SetRange(tbl.Range.End + 1, tbl.Range.End + 1)
                sel.TypeParagraph()

                return ToolResult(
                    success=True,
                    output=f"Inserted {r_count}x{c_count} table into {doc.Name}.",
                    metadata={"item_type": "table", "rows": r_count, "cols": c_count},
                )

            # ── 2. Insert Image ──
            elif t_type in ("image", "picture", "photo"):
                img_path = str(path_or_url or "").strip()
                if not img_path:
                    return ToolResult(success=False, error="path_or_url is required to insert an image.")

                # If URL, download to temporary scratch file
                if img_path.startswith("http://") or img_path.startswith("https://"):
                    import urllib.request
                    import tempfile
                    ext = os.path.splitext(img_path.split("?")[0])[1] or ".png"
                    tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=ext)
                    tmp_file.close()
                    urllib.request.urlretrieve(img_path, tmp_file.name)
                    img_path = tmp_file.name

                if not os.path.exists(img_path):
                    return ToolResult(success=False, error=f"Image file does not exist: {img_path}")

                pic = doc.InlineShapes.AddPicture(FileName=os.path.abspath(img_path), Range=sel.Range)
                sel.TypeParagraph()
                return ToolResult(
                    success=True,
                    output=f"Inserted image from '{os.path.basename(img_path)}' into {doc.Name}.",
                    metadata={"item_type": "image", "path": img_path},
                )

            # ── 3. Insert Shape ──
            elif t_type in ("shape", "box", "arrow"):
                shape_map = {
                    "rectangle": 1,           # msoShapeRectangle
                    "rounded_rectangle": 5,   # msoShapeRoundedRectangle
                    "oval": 9,                # msoShapeOval
                    "circle": 9,
                    "arrow": 33,              # msoShapeRightArrow
                    "star": 92,               # msoShape5pointStar
                    "heart": 21,              # msoShapeHeart
                }
                s_id = shape_map.get(shape_type.lower(), 1)
                shape = doc.Shapes.AddShape(s_id, 100, 100, 150, 60)
                if shape_text:
                    shape.TextFrame.TextRange.Text = str(shape_text)
                    shape.TextFrame.TextRange.Font.Bold = True

                return ToolResult(
                    success=True,
                    output=f"Inserted {shape_type} shape into {doc.Name}.",
                    metadata={"item_type": "shape", "shape_type": shape_type},
                )

            # ── 4. Insert Hyperlink ──
            elif t_type in ("hyperlink", "link", "url"):
                target_url = str(url or "").strip()
                display_text = str(text or target_url).strip()
                if not target_url:
                    return ToolResult(success=False, error="URL is required to insert hyperlink.")

                doc.Hyperlinks.Add(Anchor=sel.Range, Address=target_url, TextToDisplay=display_text)
                return ToolResult(
                    success=True,
                    output=f"Inserted hyperlink '{display_text}' -> {target_url}.",
                    metadata={"item_type": "hyperlink", "url": target_url, "text": display_text},
                )

            # ── 5. Insert Header / Footer ──
            elif t_type in ("header", "footer"):
                content_text = str(text or "").strip()
                sec = doc.Sections(1)
                if t_type == "header":
                    hdr = sec.Headers(WD_HEADER_PRIMARY)
                    hdr.Range.Text = content_text
                    if include_page_number:
                        hdr.Range.InsertAfter(" - Page ")
                        hdr.Range.Fields.Add(Range=hdr.Range, Type=33)  # wdFieldPage
                    return ToolResult(
                        success=True,
                        output=f"Updated document header: '{content_text}'.",
                        metadata={"item_type": "header", "text": content_text},
                    )
                else:
                    ftr = sec.Footers(WD_FOOTER_PRIMARY)
                    ftr.Range.Text = content_text
                    if include_page_number:
                        ftr.Range.InsertAfter(" - Page ")
                        ftr.Range.Fields.Add(Range=ftr.Range, Type=33)  # wdFieldPage
                    return ToolResult(
                        success=True,
                        output=f"Updated document footer: '{content_text}'.",
                        metadata={"item_type": "footer", "text": content_text},
                    )

            # ── 6. Page Break ──
            elif t_type in ("page_break", "break", "new_page"):
                sel.InsertBreak(Type=WD_PAGE_BREAK)
                return ToolResult(
                    success=True,
                    output="Inserted page break into document.",
                    metadata={"item_type": "page_break"},
                )

            else:
                return ToolResult(success=False, error=f"Unknown insert item type: '{item_type}'")
        except Exception as e:
            return ToolResult(success=False, error=f"Insert operation failed: {e}")


class WordPresentationTool(NexusTool):
    """Generates a professional PowerPoint presentation from the active Word document's context and saves it to the Desktop."""
    name = "word_create_presentation"
    description = (
        "Extract the structure, text, and headings from the active Microsoft Word document, "
        "synthesize a professional widescreen 16:9 PowerPoint presentation (.pptx) with key takeaways "
        "and relevant visuals, and save it directly to the user's Desktop."
    )
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        topic: Optional[str] = None,
        theme: Optional[str] = "executive_navy",
        num_slides: int = 6,
        output_path: Optional[str] = "Desktop",
        document_name: Optional[str] = None,
        hwnd: Optional[int] = None,
        target_dict: Optional[Dict[str, Any]] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            word_app, doc, win = resolve_word_target(
                document_name=document_name,
                hwnd=hwnd,
                target_dict=target_dict,
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Could not connect to Word document: {e}")

        try:
            doc_name = str(getattr(doc, "Name", "Document1"))
            clean_name = doc_name.rsplit(".", 1)[0].replace("_", " ").title()

            # 1. Extract context from Word document
            headings: List[str] = []
            paragraphs_text: List[str] = []

            try:
                for p in doc.Paragraphs:
                    try:
                        style_name = str(getattr(p.Style, "NameLocal", "")).lower()
                        t = str(p.Range.Text or "").replace("\r", " ").strip()
                        if not t:
                            continue
                        if "heading" in style_name:
                            headings.append(t)
                        elif len(t) > 20 and len(paragraphs_text) < 15:
                            paragraphs_text.append(t)
                    except Exception:
                        pass
            except Exception as read_err:
                logger.debug(f"Error reading paragraphs for presentation: {read_err}")

            # Determine presentation topic cleanly without newlines or colons
            derived_topic = topic.strip() if topic and topic.strip() else ""
            if not derived_topic:
                if headings and headings[0].lower() not in clean_name.lower():
                    derived_topic = f"{clean_name} - {headings[0]}"
                else:
                    derived_topic = clean_name

            # Ensure derived_topic is clean, single line without filesystem illegal chars
            derived_topic = re.sub(r"[\r\n\t]+", " ", derived_topic).strip()
            derived_topic = re.sub(r"[:\\/|?*]+", " - ", derived_topic)
            derived_topic = re.sub(r"\s+", " ", derived_topic).strip()[:60]
            if not derived_topic:
                derived_topic = "Executive Presentation"

            # Build enriched context summary
            context_summary = f"Source Document: {clean_name}\n"
            if headings:
                context_summary += f"Key Headings: {', '.join(headings[:8])}\n"
            if paragraphs_text:
                context_summary += "Content Excerpts:\n" + "\n".join(f"- {p[:200]}" for p in paragraphs_text[:6])

            # 2. Generate presentation via presentation_adapter
            slides_count = max(3, min(int(num_slides or 6), 12))
            sid, staging_path, pres_data = await presentation_adapter.create_presentation(
                topic=derived_topic,
                theme=theme or "executive_navy",
                num_slides=slides_count,
                context_text=context_summary,
                raw_headings=headings,
                raw_bullets=paragraphs_text,
            )

            # 3. Save directly to Desktop
            default_filename = f"{derived_topic}.pptx"
            dest = output_path or "Desktop"
            sid, saved_file = presentation_adapter.save_session(
                session_id=sid,
                output_path=dest,
                default_filename=default_filename,
            )

            # 4. Reveal in Windows File Explorer
            presentation_adapter.reveal_in_explorer(saved_file)

            msg = (
                f"Generated {len(pres_data.slides)}-slide PowerPoint presentation '{pres_data.title}' "
                f"from '{doc_name}' and saved it to your Desktop: '{saved_file}'."
            )

            return ToolResult(
                success=True,
                output=msg,
                metadata={
                    "file_path": str(saved_file),
                    "document_name": doc_name,
                    "topic": pres_data.topic,
                    "title": pres_data.title,
                    "slide_count": len(pres_data.slides),
                    "theme": pres_data.theme,
                },
            )
        except Exception as exc:
            logger.error(f"Failed to create presentation from Word document: {exc}")
            return ToolResult(success=False, error=f"Failed to create presentation from Word document: {exc}")


# Register tools
word_format_text_tool = WordFormatTextTool()
word_clipboard_op_tool = WordClipboardOpTool()
word_find_replace_tool = WordFindReplaceTool()
word_format_paragraph_tool = WordFormatParagraphTool()
word_insert_tool = WordInsertTool()
word_presentation_tool = WordPresentationTool()

