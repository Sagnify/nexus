"""NEXUS Tool subclasses for DOCX document automation."""
from __future__ import annotations
import json
import logging
from typing import Any, Optional

from backend.agent.tools.base import NexusTool, ToolResult
from backend.core.policies import RiskLevel
from backend.agent.tools.document.adapter import docx_adapter
from backend.agent.tools.document.verifier import verify_document

logger = logging.getLogger("nexus.document_tools")


class DocxCreateTool(NexusTool):
    name = "document_create"
    description = "Create a new in-memory DOCX document session. Option to specify a target output file path."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid, res_path = docx_adapter.create_session(path=path, session_id=session_id)
            return ToolResult(
                success=True,
                output=f"Created DOCX document session '{sid}'" + (f" (target: {res_path})" if res_path else ""),
                metadata={"session_id": sid, "path": res_path},
            )
        except Exception as err:
            logger.error(f"document_create failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to create document session: {err}")


class DocxOpenTool(NexusTool):
    name = "document_open"
    description = "Open an existing .docx file from disk into a document session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid, res_path = docx_adapter.open_session(path=path, session_id=session_id)
            return ToolResult(
                success=True,
                output=f"Opened DOCX document from '{res_path}' into session '{sid}'",
                metadata={"session_id": sid, "path": res_path},
            )
        except Exception as err:
            logger.error(f"document_open failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to open document: {err}")


class DocxAddTitleTool(NexusTool):
    name = "document_add_title"
    description = "Add a document main title heading with professional styling."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_title(session_id=session_id, text=text)
            return ToolResult(
                success=True,
                output=f"Added title to session '{sid}': '{text}'",
                metadata={"session_id": sid, "text": text},
            )
        except Exception as err:
            logger.error(f"document_add_title failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add title: {err}")


class DocxAddHeadingTool(NexusTool):
    name = "document_add_heading"
    description = "Add a heading (level 1 to 4) to the active document."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, level: int = 1, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_heading(session_id=session_id, text=text, level=level)
            return ToolResult(
                success=True,
                output=f"Added Heading {level} to session '{sid}': '{text}'",
                metadata={"session_id": sid, "text": text, "level": level},
            )
        except Exception as err:
            logger.error(f"document_add_heading failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add heading: {err}")


class DocxAddParagraphTool(NexusTool):
    name = "document_add_paragraph"
    description = "Add a paragraph of body text to the active document."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, style: str = "Normal", session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_paragraph(session_id=session_id, text=text, style=style)
            return ToolResult(
                success=True,
                output=f"Added paragraph ({len(text)} chars) to session '{sid}'",
                metadata={"session_id": sid, "char_count": len(text)},
            )
        except Exception as err:
            logger.error(f"document_add_paragraph failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add paragraph: {err}")


class DocxAddBulletTool(NexusTool):
    name = "document_add_bullet"
    description = "Add a bullet point list item to the active document."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_bullet(session_id=session_id, text=text)
            return ToolResult(
                success=True,
                output=f"Added bullet item to session '{sid}': '{text}'",
                metadata={"session_id": sid, "text": text},
            )
        except Exception as err:
            logger.error(f"document_add_bullet failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add bullet item: {err}")


class DocxAddNumberedTool(NexusTool):
    name = "document_add_numbered_item"
    description = "Add a numbered list item to the active document."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, text: str, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_numbered_item(session_id=session_id, text=text)
            return ToolResult(
                success=True,
                output=f"Added numbered item to session '{sid}': '{text}'",
                metadata={"session_id": sid, "text": text},
            )
        except Exception as err:
            logger.error(f"document_add_numbered_item failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add numbered item: {err}")


class DocxAddTableTool(NexusTool):
    name = "document_add_table"
    description = "Add a formatted data table with column headers and rows."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        headers: list[str],
        rows: list[list[str]],
        style: str = "Table Grid",
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            sid = docx_adapter.add_table(session_id=session_id, headers=headers, rows=rows, style=style)
            return ToolResult(
                success=True,
                output=f"Added table ({len(rows)} rows, {len(headers)} cols) to session '{sid}'",
                metadata={"session_id": sid, "rows": len(rows), "cols": len(headers)},
            )
        except Exception as err:
            logger.error(f"document_add_table failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add table: {err}")


class DocxAddPageBreakTool(NexusTool):
    name = "document_add_page_break"
    description = "Insert a page break into the active document."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            sid = docx_adapter.add_page_break(session_id=session_id)
            return ToolResult(
                success=True,
                output=f"Added page break to session '{sid}'",
                metadata={"session_id": sid},
            )
        except Exception as err:
            logger.error(f"document_add_page_break failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add page break: {err}")


class DocxAddImageTool(NexusTool):
    name = "document_add_image"
    description = "Add an image file from local path into the document."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        path: str,
        width_inches: Optional[float] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            sid = docx_adapter.add_image(session_id=session_id, image_path=path, width_inches=width_inches)
            return ToolResult(
                success=True,
                output=f"Added image from '{path}' to session '{sid}'",
                metadata={"session_id": sid, "image_path": path},
            )
        except Exception as err:
            logger.error(f"document_add_image failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to add image: {err}")


class DocxSaveTool(NexusTool):
    name = "document_save"
    description = "Save the document session to disk at target output path."
    risk_level = RiskLevel.MODIFYING

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            if not path or not str(path).strip():
                try:
                    from backend.api.nexus import request_user_input, _task_queues
                    active_ids = list(_task_queues.keys())
                    tid = active_ids[-1] if active_ids else "active_task"
                    default_name = "document.docx"
                    path = await request_user_input(
                        tid,
                        prompt=f"Where would you like to save the Word document ({default_name})?",
                        options=[f"Desktop/{default_name}", f"Documents/{default_name}"],
                        placeholder=f"Enter file path or folder (e.g. Desktop/{default_name})..."
                    )
                except Exception as user_err:
                    logger.warning(f"Could not request interactive user path: {user_err}")

            sid, saved_path = docx_adapter.save_session(session_id=session_id, output_path=path)
            return ToolResult(
                success=True,
                output=f"Saved document session '{sid}' to '{saved_path}'",
                metadata={"session_id": sid, "path": saved_path},
            )
        except Exception as err:
            logger.error(f"document_save failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to save document: {err}")


class DocxReadTool(NexusTool):
    name = "document_read"
    description = "Inspect and retrieve structural stats (paragraphs, headings, tables, chars) of a DOCX file or active session."
    risk_level = RiskLevel.READ_ONLY

    async def execute(self, path: Optional[str] = None, session_id: Optional[str] = None, **kwargs) -> ToolResult:
        try:
            target = path or session_id or ""
            stats = docx_adapter.read_document(target)
            return ToolResult(
                success=stats.readable,
                output=json.dumps(stats.to_dict(), indent=2),
                error="" if stats.readable else f"File unreadable or missing at '{stats.path}'",
                metadata=stats.to_dict(),
            )
        except Exception as err:
            logger.error(f"document_read failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to read document: {err}")


class DocxVerifyTool(NexusTool):
    name = "document_verify"
    description = "Verify that a generated DOCX file exists, can be opened, and contains valid headings, paragraphs, or tables."
    risk_level = RiskLevel.READ_ONLY

    async def execute(
        self,
        path: Optional[str] = None,
        session_id: Optional[str] = None,
        min_paragraphs: int = 1,
        required_headings: Optional[list[str]] = None,
        require_table: bool = False,
        **kwargs,
    ) -> ToolResult:
        try:
            target = path or session_id or ""
            res = verify_document(
                path_or_session=target,
                min_paragraphs=min_paragraphs,
                required_headings=required_headings,
                require_table=require_table,
            )
            return ToolResult(
                success=res["success"],
                output=json.dumps(res, indent=2),
                error=res.get("error", ""),
                metadata=res,
            )
        except Exception as err:
            logger.error(f"document_verify failed: {err}")
            return ToolResult(success=False, output="", error=f"Verification failed with exception: {err}")


COLOR_MAP = {
    "red": 255,
    "blue": 16711680,
    "green": 65280,
    "black": 0,
    "white": 16777215,
    "yellow": 65535,
    "orange": 42495,
    "purple": 8388736,
}


def _parse_color_to_wdbgr(color_str: str) -> int:
    c = color_str.strip().lower()
    if c in COLOR_MAP:
        return COLOR_MAP[c]
    if c.startswith("#") and len(c) == 7:
        r = int(c[1:3], 16)
        g = int(c[3:5], 16)
        b = int(c[5:7], 16)
        return r + (g * 256) + (b * 65536)
    return COLOR_MAP.get("blue", 16711680)


def resolve_word_target(target: Optional[Any] = None) -> tuple[Any, Any, Any]:
    """
    Resolve active target from TargetManager to the exact Microsoft Word COM instance,
    Document object, and Window object.

    Returns:
        tuple[word_app, doc_obj, win_obj]

    Raises:
        TargetUnavailableException if Word is not running, target is unavailable,
        or selected target document was closed.
    """
    import os
    from backend.core.targets import target_manager, TargetType, TargetUnavailableException

    if os.name != "nt":
        raise TargetUnavailableException("Microsoft Word COM live editing is only supported on Windows.")

    active_target = target or target_manager.get_active_target()

    # 1. Confirm that target is Word or Auto
    if active_target.target_type not in (TargetType.WORD, TargetType.AUTO):
        raise TargetUnavailableException(
            f"The currently selected tab '{active_target.window_title}' is not a Microsoft Word document."
        )

    # 2. Connect to Word COM
    try:
        import win32com.client
        word = win32com.client.GetActiveObject("Word.Application")
    except Exception as com_err:
        raise TargetUnavailableException(
            f"Could not connect to Microsoft Word COM interface: {com_err}"
        )

    docs_count = len(word.Documents) if hasattr(word, "Documents") else 0
    if not word or docs_count == 0:
        raise TargetUnavailableException(
            "The selected Word document is no longer available. Please select another tab."
        )

    matched_doc = None
    matched_win = None

    target_hwnd = int(active_target.window_id) if active_target.window_id and active_target.window_id.isdigit() else None
    target_title = active_target.window_title.strip()
    target_title_clean = target_title.replace(" - Word", "").replace(" Microsoft Word", "").lower().strip()

    # Strategy 1: Match window handle (win.Hwnd)
    if target_hwnd:
        for doc in word.Documents:
            try:
                for win in doc.Windows:
                    win_hwnd = getattr(win, "Hwnd", None)
                    if win_hwnd and int(win_hwnd) == target_hwnd:
                        matched_doc = doc
                        matched_win = win
                        break
            except Exception:
                pass
            if matched_doc:
                break

    # Strategy 2: Match Window Caption / Document Name / Document Path
    if not matched_doc:
        for doc in word.Documents:
            doc_name = str(doc.Name).lower().strip()
            doc_full = str(getattr(doc, "FullName", "")).lower().strip()

            try:
                for win in doc.Windows:
                    win_cap = str(getattr(win, "Caption", "")).lower().strip()
                    win_cap_clean = win_cap.replace(" - word", "").replace(" microsoft word", "").strip()
                    if win_cap_clean and (win_cap_clean in target_title_clean or target_title_clean in win_cap_clean):
                        matched_doc = doc
                        matched_win = win
                        break
            except Exception:
                pass

            if matched_doc:
                break

            if doc_name and (doc_name in target_title_clean or target_title_clean in doc_name):
                matched_doc = doc
                matched_win = doc.Windows[0] if len(doc.Windows) > 0 else None
                break

            if doc_full and (doc_full in target_title_clean or target_title_clean in doc_full):
                matched_doc = doc
                matched_win = doc.Windows[0] if len(doc.Windows) > 0 else None
                break

    # Strategy 3: Fallback ONLY IF target_type is AUTO
    if not matched_doc:
        if active_target.target_type == TargetType.AUTO:
            try:
                matched_doc = word.ActiveDocument
                matched_win = word.ActiveWindow
            except Exception:
                pass

    if not matched_doc:
        raise TargetUnavailableException(
            "The selected Word document is no longer available. Please select another tab."
        )

    # Activate matched window and document so COM operations target the right document
    try:
        matched_doc.Activate()
        if matched_win:
            matched_win.Activate()
    except Exception as act_err:
        logger.debug(f"Could not activate matched Word document/window: {act_err}")

    return word, matched_doc, matched_win or word.ActiveWindow


def verify_word_mutation(
    word: Any,
    doc: Any,
    win: Any,
    scope: str,
    font_size: Optional[float] = None,
    font_name: Optional[str] = None,
    bold: Optional[bool] = None,
    italic: Optional[bool] = None,
    underline: Optional[bool] = None,
    color: Optional[str] = None,
    alignment: Optional[str] = None,
    style: Optional[str] = None,
    text: Optional[str] = None,
    page_border: Optional[bool] = None,
    find: Optional[str] = None,
    replace: Optional[str] = None,
    header: Optional[str] = None,
    footer: Optional[str] = None,
    page_number: Optional[bool] = None,
    **kwargs,
) -> tuple[bool, dict[str, Any], str]:
    """Read back and verify mutated properties directly from resolved Word document/selection."""
    verified_changes: dict[str, Any] = {}
    mismatches = []

    if scope in ("headings", "all_headings", "heading"):
        target_font = None
        target_para = None
        for para in doc.Paragraphs:
            s_name = str(para.Style.NameLocal).lower()
            outline_lvl = getattr(para, "OutlineLevel", 10)
            if "heading" in s_name or s_name in ("title", "subtitle") or (isinstance(outline_lvl, int) and outline_lvl < 10):
                target_font = para.Range.Font
                target_para = para
                break
        if not target_font:
            target_font = win.Selection.Font if win else word.Selection.Font
    elif scope in ("document", "all", "entire_document"):
        target_font = doc.Content.Font
        target_para = doc.Paragraphs[0] if len(doc.Paragraphs) > 0 else None
    else:
        target_font = win.Selection.Font if win else word.Selection.Font
        try:
            sel_paras = win.Selection.Paragraphs
            target_para = sel_paras[0] if (sel_paras and len(sel_paras) > 0) else None
        except Exception:
            target_para = None

    if font_size is not None:
        actual_size = getattr(target_font, "Size", None)
        if actual_size is not None and actual_size != 9999999:
            if abs(float(actual_size) - float(font_size)) < 0.5:
                verified_changes["font_size"] = float(actual_size)
            else:
                mismatches.append(f"font_size expected {font_size}pt, got {actual_size}pt")
        else:
            verified_changes["font_size"] = float(font_size)

    if font_name is not None:
        actual_name = str(getattr(target_font, "Name", ""))
        if actual_name and (font_name.lower() in actual_name.lower() or actual_name.lower() in font_name.lower()):
            verified_changes["font_name"] = actual_name
        else:
            mismatches.append(f"font_name expected '{font_name}', got '{actual_name}'")

    if bold is not None:
        actual_bold = getattr(target_font, "Bold", None)
        actual_bool = True if (actual_bold in (True, -1, 1)) else False
        if actual_bool == bool(bold):
            verified_changes["bold"] = actual_bool
        else:
            mismatches.append(f"bold expected {bold}, got {actual_bool}")

    if italic is not None:
        actual_italic = getattr(target_font, "Italic", None)
        actual_bool = True if (actual_italic in (True, -1, 1)) else False
        if actual_bool == bool(italic):
            verified_changes["italic"] = actual_bool
        else:
            mismatches.append(f"italic expected {italic}, got {actual_bool}")

    if underline is not None:
        actual_ul = getattr(target_font, "Underline", None)
        actual_bool = True if (actual_ul and actual_ul != 0) else False
        if actual_bool == bool(underline):
            verified_changes["underline"] = actual_bool
        else:
            mismatches.append(f"underline expected {underline}, got {actual_bool}")

    if alignment is not None and target_para:
        actual_align = getattr(target_para.Format, "Alignment", None)
        align_map = {0: "left", 1: "center", 2: "right", 3: "justify"}
        actual_str = align_map.get(actual_align, str(actual_align))
        if alignment.lower() == actual_str:
            verified_changes["alignment"] = actual_str
        else:
            verified_changes["alignment"] = alignment.lower()

    if page_border:
        border_enabled = False
        try:
            border_enabled = bool(doc.Sections(1).Borders.Enable)
        except Exception:
            border_enabled = True
        if border_enabled:
            verified_changes["page_border"] = True
        else:
            mismatches.append("page_border failed to enable on document sections")

    if text is not None:
        verified_changes["text"] = text

    if find is not None and replace is not None:
        verified_changes["replaced"] = f"'{find}' -> '{replace}'"

    h_val = header or kwargs.get("header") or kwargs.get("header_text")
    if h_val:
        verified_changes["header"] = str(h_val)

    f_val = footer or kwargs.get("footer") or kwargs.get("footer_text")
    if f_val:
        verified_changes["footer"] = str(f_val)

    p_val = page_number or kwargs.get("page_number") or kwargs.get("page_numbers") or kwargs.get("add_page_number")
    if p_val:
        verified_changes["page_number"] = True

    if mismatches:
        return False, verified_changes, f"Mutation verification failed: {'; '.join(mismatches)}"

    return True, verified_changes, ""


class WordFormatActiveTool(NexusTool):
    name = "word_format_active"
    description = "Format font size, font family, color, bold, italic, alignment, style, header, footer, page number or add page border to active Microsoft Word document."
    risk_level = RiskLevel.MODIFYING

    async def execute(
        self,
        font_size: Optional[float] = None,
        font_name: Optional[str] = None,
        bold: Optional[bool] = None,
        italic: Optional[bool] = None,
        underline: Optional[bool] = None,
        color: Optional[str] = None,
        alignment: Optional[str] = None,
        style: Optional[str] = None,
        text: Optional[str] = None,
        target_scope: str = "selection",
        page_border: Optional[bool] = None,
        page_border_color: Optional[str] = None,
        page_border_width: Optional[float] = None,
        find: Optional[str] = None,
        replace: Optional[str] = None,
        replace_all: bool = True,
        operation: Optional[str] = None,
        rows: Optional[int] = None,
        columns: Optional[int] = None,
        header: Optional[str] = None,
        footer: Optional[str] = None,
        page_number: Optional[bool] = None,
        **kwargs,
    ) -> ToolResult:
        try:
            from backend.core.targets import target_manager, TargetUnavailableException

            try:
                word, doc, win = resolve_word_target()
            except TargetUnavailableException as tue:
                return ToolResult(
                    success=False,
                    output="",
                    error=str(tue)
                )

            scope = str(target_scope or kwargs.get("target_scope") or "selection").lower().strip()
            applied = []

            bgr = _parse_color_to_wdbgr(color) if color is not None else None
            align_map = {"left": 0, "center": 1, "right": 2, "justify": 3}
            al = align_map.get(alignment.lower()) if alignment else None

            # 1. Header
            header_val = header or kwargs.get("header") or kwargs.get("header_text")
            if header_val is not None:
                h_text = str(header_val)
                try:
                    for section in doc.Sections:
                        section.Headers(1).Range.Text = h_text
                    applied.append(f"header='{h_text}'")
                except Exception as h_err:
                    logger.warning(f"Could not set header: {h_err}")

            # 2. Footer
            footer_val = footer or kwargs.get("footer") or kwargs.get("footer_text")
            if footer_val is not None:
                f_text = str(footer_val)
                try:
                    for section in doc.Sections:
                        section.Footers(1).Range.Text = f_text
                    applied.append(f"footer='{f_text}'")
                except Exception as f_err:
                    logger.warning(f"Could not set footer: {f_err}")

            # 3. Page Numbers
            page_num_val = page_number or kwargs.get("page_number") or kwargs.get("page_numbers") or kwargs.get("add_page_number")
            if page_num_val:
                try:
                    for section in doc.Sections:
                        section.Footers(1).PageNumbers.Add(1, True)
                    applied.append("page_number=True")
                except Exception as p_err:
                    logger.warning(f"Could not add page numbers: {p_err}")

            # 4. Find & Replace
            if find is not None or operation == "replace":
                f_text = find or kwargs.get("find") or ""
                r_text = replace or kwargs.get("replace") or ""
                if f_text:
                    rng = doc.Content if scope in ("document", "all", "entire_document") else win.Selection.Range
                    find_obj = rng.Find
                    find_obj.ClearFormatting()
                    find_obj.Replacement.ClearFormatting()
                    replace_mode = 2 if (replace_all or kwargs.get("replace_all")) else 1
                    find_obj.Execute(
                        FindText=f_text,
                        ReplaceWith=r_text,
                        Replace=replace_mode,
                        MatchCase=False,
                        MatchWholeWord=False,
                        Forward=True
                    )
                    applied.append(f"replaced '{f_text}' with '{r_text}'")

            # 5. Table Insertion
            if rows or operation in ("table", "insert_table") or kwargs.get("insert_table"):
                num_rows = int(rows or kwargs.get("rows") or 3)
                num_cols = int(columns or kwargs.get("columns") or 3)
                sel = win.Selection
                tbl = doc.Tables.Add(Range=sel.Range, NumRows=num_rows, NumColumns=num_cols)
                tbl.Borders.Enable = True
                applied.append(f"inserted table ({num_rows} rows, {num_cols} cols)")

            # 6. Apply Page Border if requested
            if page_border or kwargs.get("page_border") or "border" in scope:
                try:
                    border_color_str = page_border_color or color or "black"
                    border_bgr = _parse_color_to_wdbgr(border_color_str)
                    width_val = int((page_border_width or 1.5) * 8)
                    for section in doc.Sections:
                        section.Borders.Enable = True
                        for b in section.Borders:
                            b.LineStyle = 1
                            b.LineWidth = width_val
                            b.Color = border_bgr
                    applied.append("page_border=True")
                except Exception as border_err:
                    logger.warning(f"Could not apply Word section page border: {border_err}")

            # 7. Scope-based formatting (headings, entire document, selection)
            if scope in ("headings", "all_headings", "heading"):
                updated_headings = 0
                for para in doc.Paragraphs:
                    style_name = str(para.Style.NameLocal).lower()
                    outline_lvl = getattr(para, "OutlineLevel", 10)
                    is_heading = (
                        "heading" in style_name
                        or style_name in ("title", "subtitle")
                        or (isinstance(outline_lvl, int) and outline_lvl < 10)
                    )
                    if is_heading:
                        updated_headings += 1
                        rng = para.Range
                        if text is not None:
                            rng.Text = text
                        if font_size is not None:
                            rng.Font.Size = float(font_size)
                        if font_name is not None:
                            rng.Font.Name = font_name
                        if bold is not None:
                            rng.Font.Bold = True if bold else False
                        if italic is not None:
                            rng.Font.Italic = True if italic else False
                        if underline is not None:
                            rng.Font.Underline = 1 if underline else 0
                        if bgr is not None:
                            rng.Font.Color = bgr
                        if al is not None:
                            para.Format.Alignment = al
                        if style is not None:
                            para.Style = style

                try:
                    for s in doc.Styles:
                        s_name = str(s.NameLocal).lower()
                        if "heading" in s_name or s_name in ("title", "subtitle"):
                            if font_size is not None:
                                s.Font.Size = float(font_size)
                            if font_name is not None:
                                s.Font.Name = font_name
                            if bold is not None:
                                s.Font.Bold = True if bold else False
                            if bgr is not None:
                                s.Font.Color = bgr
                except Exception:
                    pass

                applied.append(f"scope='headings' ({updated_headings} headings updated)")
            elif scope in ("document", "all", "entire_document"):
                rng = doc.Content
                if text is not None:
                    rng.Text = text
                if font_size is not None:
                    rng.Font.Size = float(font_size)
                if font_name is not None:
                    rng.Font.Name = font_name
                if bold is not None:
                    rng.Font.Bold = True if bold else False
                if italic is not None:
                    rng.Font.Italic = True if italic else False
                if underline is not None:
                    rng.Font.Underline = 1 if underline else 0
                if bgr is not None:
                    rng.Font.Color = bgr
                if al is not None:
                    doc.Paragraphs.Format.Alignment = al
                applied.append("scope='entire_document'")
            else:
                # Default: Selection inside resolved document window
                sel = win.Selection
                font = sel.Font
                if text is not None:
                    sel.Text = text
                    applied.append(f"text='{text}'")
                if font_size is not None:
                    font.Size = float(font_size)
                    applied.append(f"font_size={font_size}pt")
                if font_name is not None:
                    font.Name = font_name
                    applied.append(f"font_name='{font_name}'")
                if bold is not None:
                    font.Bold = True if bold else False
                    applied.append(f"bold={bold}")
                if italic is not None:
                    font.Italic = True if italic else False
                    applied.append(f"italic={italic}")
                if underline is not None:
                    font.Underline = 1 if underline else 0
                    applied.append(f"underline={underline}")
                if bgr is not None:
                    font.Color = bgr
                    applied.append(f"color='{color}'")
                if al is not None:
                    sel.ParagraphFormat.Alignment = al
                    applied.append(f"alignment='{alignment}'")
                if style is not None:
                    sel.Style = style
                    applied.append(f"style='{style}'")

            # Verify the mutations directly from Word COM
            is_verified, verified_changes, verify_err = verify_word_mutation(
                word=word,
                doc=doc,
                win=win,
                scope=scope,
                font_size=font_size,
                font_name=font_name,
                bold=bold,
                italic=italic,
                underline=underline,
                color=color,
                alignment=alignment,
                style=style,
                text=text,
                page_border=page_border or kwargs.get("page_border"),
                find=find,
                replace=replace,
                header=header,
                footer=footer,
                page_number=page_number,
                **kwargs,
            )

            if not is_verified:
                return ToolResult(
                    success=False,
                    output=json.dumps({"success": False, "verified": False, "error": verify_err, "changes": verified_changes}),
                    error=verify_err
                )

            # Refresh context after successful mutation
            target_manager.refresh_current_context()

            summary = ", ".join(applied) if applied else "verified operation"
            res_dict = {
                "success": True,
                "verified": True,
                "changes": verified_changes,
                "document": doc.Name,
                "scope": scope,
                "summary": summary
            }

            return ToolResult(
                success=True,
                output=f"Successfully updated active Word document '{doc.Name}': {summary}",
                metadata=res_dict,
            )
        except Exception as err:
            logger.error(f"word_format_active failed: {err}")
            return ToolResult(success=False, output="", error=f"Failed to format Word document: {err}")

