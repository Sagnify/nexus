"""NEXUS Target Discovery and Context Management System."""
from __future__ import annotations
import ctypes
import ctypes.wintypes
import datetime
import json
import logging
import os
import io
import base64
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from pydantic import BaseModel
import psutil
from PIL import Image

logger = logging.getLogger("nexus.targets")


class TargetType(str, Enum):
    AUTO = "auto"
    ANTIGRAVITY = "antigravity"
    WORD = "word"
    EXCEL = "excel"
    BROWSER = "browser"
    EXPLORER = "explorer"
    PAINT = "paint"
    GENERIC = "generic"


class Target(BaseModel):
    id: str
    application: str
    window_title: str
    process_name: str
    window_id: Optional[str] = None
    target_type: TargetType
    icon: Optional[str] = None
    icon_data: Optional[str] = None  # Real base64 PNG data URL extracted from native computer executable
    exe_path: Optional[str] = None
    browser_tab_id: Optional[int] = None
    browser_url: Optional[str] = None


class TargetContext(BaseModel):
    target_id: str
    application: str
    window_title: str
    target_type: TargetType
    timestamp: str
    details: dict[str, Any] = {}


class TargetUnavailableException(Exception):
    """Raised when the selected target window is closed or no longer accessible."""
    pass


class TargetManager:
    """Singleton manager for target discovery, active target session, and lazy context acquisition."""

    _instance: Optional[TargetManager] = None

    def __init__(self):
        self._active_target_id: str = "auto"
        self._cached_targets: dict[str, Target] = {}
        self._icon_cache: dict[str, str] = {}
        self._active_context: Optional[TargetContext] = None
        self._init_default_target()

    @classmethod
    def get_instance(cls) -> TargetManager:
        if cls._instance is None:
            cls._instance = TargetManager()
        return cls._instance

    def _extract_icon_base64(self, exe_path: str = "", hwnd: int = 0) -> Optional[str]:
        """Extract the real native application icon from the Windows executable or window handle."""
        cache_key = exe_path or str(hwnd)
        if cache_key in self._icon_cache:
            return self._icon_cache[cache_key]

        if os.name != "nt":
            return None

        hIcon = None
        user32 = ctypes.windll.user32
        shell32 = ctypes.windll.shell32
        gdi32 = ctypes.windll.gdi32

        # 1. Try extracting icon from executable file via SHGetFileInfoW
        if exe_path and os.path.exists(exe_path):
            try:
                class SHFILEINFOW(ctypes.Structure):
                    _fields_ = [
                        ('hIcon', ctypes.wintypes.HICON),
                        ('iIcon', ctypes.c_int),
                        ('dwAttributes', ctypes.wintypes.DWORD),
                        ('szDisplayName', ctypes.wintypes.WCHAR * 260),
                        ('szTypeName', ctypes.wintypes.WCHAR * 80)
                    ]
                shell32.SHGetFileInfoW.argtypes = [
                    ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD,
                    ctypes.POINTER(SHFILEINFOW), ctypes.wintypes.UINT, ctypes.wintypes.UINT
                ]
                shell32.SHGetFileInfoW.restype = ctypes.c_void_p

                sfi = SHFILEINFOW()
                # SHGFI_ICON (0x100) | SHGFI_SMALLICON (0x1) or SHGFI_LARGEICON (0x0)
                res = shell32.SHGetFileInfoW(exe_path, 0, ctypes.byref(sfi), ctypes.sizeof(sfi), 0x100 | 0x0)
                if res and sfi.hIcon:
                    hIcon = sfi.hIcon
            except Exception as e:
                logger.debug(f"SHGetFileInfoW error for {exe_path}: {e}")

        # 2. Fallback: Try WM_GETICON or GetClassLongPtrW from hwnd
        if not hIcon and hwnd:
            try:
                WM_GETICON = 0x7F
                ICON_BIG = 1
                ICON_SMALL2 = 2
                res = user32.SendMessageW(hwnd, WM_GETICON, ICON_BIG, 0)
                if not res:
                    res = user32.SendMessageW(hwnd, WM_GETICON, ICON_SMALL2, 0)
                if not res:
                    GCLP_HICON = -14
                    res = user32.GetClassLongPtrW(hwnd, GCLP_HICON)
                if res:
                    hIcon = res
            except Exception:
                pass

        if not hIcon:
            return None

        # 3. Convert HICON to 32x32 PNG base64 data URL
        try:
            class ICONINFO(ctypes.Structure):
                _fields_ = [
                    ('fIcon', ctypes.wintypes.BOOL),
                    ('xHotspot', ctypes.wintypes.DWORD),
                    ('yHotspot', ctypes.wintypes.DWORD),
                    ('hbmMask', ctypes.wintypes.HBITMAP),
                    ('hbmColor', ctypes.wintypes.HBITMAP)
                ]

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.wintypes.DWORD),
                    ('biWidth', ctypes.wintypes.LONG),
                    ('biHeight', ctypes.wintypes.LONG),
                    ('biPlanes', ctypes.wintypes.WORD),
                    ('biBitCount', ctypes.wintypes.WORD),
                    ('biCompression', ctypes.wintypes.DWORD),
                    ('biSizeImage', ctypes.wintypes.DWORD),
                    ('biXPelsPerMeter', ctypes.wintypes.LONG),
                    ('biYPelsPerMeter', ctypes.wintypes.LONG),
                    ('biClrUsed', ctypes.wintypes.DWORD),
                    ('biClrImportant', ctypes.wintypes.DWORD)
                ]

            user32.GetIconInfo.argtypes = [ctypes.wintypes.HICON, ctypes.POINTER(ICONINFO)]
            user32.GetIconInfo.restype = ctypes.wintypes.BOOL
            user32.GetDC.argtypes = [ctypes.wintypes.HWND]
            user32.GetDC.restype = ctypes.wintypes.HDC
            user32.ReleaseDC.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.HDC]
            user32.ReleaseDC.restype = ctypes.c_int
            gdi32.GetDIBits.argtypes = [
                ctypes.wintypes.HDC, ctypes.wintypes.HBITMAP, ctypes.wintypes.UINT, ctypes.wintypes.UINT,
                ctypes.c_void_p, ctypes.POINTER(BITMAPINFOHEADER), ctypes.wintypes.UINT
            ]
            gdi32.GetDIBits.restype = ctypes.c_int
            gdi32.DeleteObject.argtypes = [ctypes.wintypes.HGDIOBJ]
            gdi32.DeleteObject.restype = ctypes.wintypes.BOOL
            user32.DestroyIcon.argtypes = [ctypes.wintypes.HICON]
            user32.DestroyIcon.restype = ctypes.wintypes.BOOL

            icon_info = ICONINFO()
            if not user32.GetIconInfo(hIcon, ctypes.byref(icon_info)):
                return None

            hdc = user32.GetDC(0)
            bih = BITMAPINFOHEADER()
            bih.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bih.biWidth = 32
            bih.biHeight = -32  # Top-down bitmap
            bih.biPlanes = 1
            bih.biBitCount = 32
            bih.biCompression = 0

            buf = ctypes.create_string_buffer(32 * 32 * 4)
            gdi32.GetDIBits(hdc, icon_info.hbmColor, 0, 32, ctypes.byref(buf), ctypes.byref(bih), 0)
            user32.ReleaseDC(0, hdc)
            gdi32.DeleteObject(icon_info.hbmColor)
            gdi32.DeleteObject(icon_info.hbmMask)

            raw = bytearray(buf.raw)
            has_alpha = any(raw[i] > 0 for i in range(3, len(raw), 4))
            for i in range(0, len(raw), 4):
                b, g, r, a = raw[i], raw[i+1], raw[i+2], raw[i+3]
                raw[i] = r
                raw[i+1] = g
                raw[i+2] = b
                if not has_alpha:
                    raw[i+3] = 255 if (r > 0 or g > 0 or b > 0) else 0

            img = Image.frombytes('RGBA', (32, 32), bytes(raw))
            out = io.BytesIO()
            img.save(out, format='PNG')
            b64_str = base64.b64encode(out.getvalue()).decode('utf-8')
            data_url = f"data:image/png;base64,{b64_str}"
            self._icon_cache[cache_key] = data_url
            return data_url
        except Exception as err:
            logger.debug(f"Error converting HICON to base64: {err}")
            return None
        finally:
            try:
                user32.DestroyIcon(hIcon)
            except Exception:
                pass

    def _init_default_target(self):
        default_auto = Target(
            id="auto",
            application="Auto / General",
            window_title="General Search & AI Assistant Mode",
            process_name="none",
            target_type=TargetType.AUTO,
            icon="globe",
        )
        self._cached_targets["auto"] = default_auto
        if self._active_target_id == "auto":
            self.acquire_context("auto")

    def discover_targets(self) -> list[Target]:
        """Lightweight target discovery: discover open windows & browser tabs without heavy context extraction."""
        discovered: list[Target] = []

        # 1. Auto / General Mode is always option #1
        auto_target = Target(
            id="auto",
            application="Auto / General",
            window_title="General Search & AI Assistant Mode",
            process_name="none",
            target_type=TargetType.AUTO,
            icon="globe",
        )
        discovered.append(auto_target)
        self._cached_targets["auto"] = auto_target

        # 2. Discover real running desktop application windows via Win32 ctypes
        if os.name == "nt":
            os_targets = self._discover_win32_windows()
            has_antigravity = any(t.target_type == TargetType.ANTIGRAVITY for t in os_targets)
            for t in os_targets:
                discovered.append(t)
                self._cached_targets[t.id] = t

            # If Antigravity IDE is running but has no standalone window detected, add workspace fallback
            if not has_antigravity:
                antigravity_exe = ""
                try:
                    for p in psutil.process_iter(['name', 'exe']):
                        try:
                            if 'antigravity' in (p.info.get('name') or '').lower():
                                antigravity_exe = p.info.get('exe') or ""
                                break
                        except Exception:
                            pass
                except Exception:
                    pass

                if antigravity_exe:
                    anti_icon = self._extract_icon_base64(antigravity_exe)
                    antigravity_target = Target(
                        id="antigravity",
                        application="Antigravity",
                        window_title="Antigravity — Active Workspace",
                        process_name="antigravity.exe",
                        target_type=TargetType.ANTIGRAVITY,
                        icon="sparkles",
                        icon_data=anti_icon,
                        exe_path=antigravity_exe or None,
                    )
                    discovered.append(antigravity_target)
                    self._cached_targets["antigravity"] = antigravity_target

        # 3. Discover Chrome Browser Tabs if Extension Bridge is active
        try:
            from backend.agent.tools.web_automation.extension_bridge import extension_bridge
            if extension_bridge.is_connected():
                pass
        except Exception as e:
            logger.debug(f"Could not check extension bridge for tabs: {e}")

        return discovered

    def _discover_win32_windows(self) -> list[Target]:
        results: list[Target] = []
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
        GW_OWNER = 4
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000

        class RECT(ctypes.Structure):
            _fields_ = [('left', ctypes.c_long), ('top', ctypes.c_long), ('right', ctypes.c_long), ('bottom', ctypes.c_long)]

        def get_window_text(hwnd) -> str:
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value

        ignored_titles = {
            "Program Manager", "Default IME", "MSCTFIME UI", "Settings",
            "Windows Input Experience", "NEXUS", "NEXUS Spotlight"
        }

        seen_hwnds = set()

        def enum_proc(hwnd, lparam):
            if not user32.IsWindowVisible(hwnd):
                return 1
            title = get_window_text(hwnd).strip()
            if not title or title in ignored_titles or title.startswith("NEXUS"):
                return 1

            title_lower = title.lower()
            if any(ig in title_lower for ig in ['nvidia geforce overlay', 'program manager', 'default ime', 'msctfime ui', 'windows input experience']):
                return 1

            # Windows Alt-Tab filter: exclude toolwindows, child/owned windows, and zero-size windows
            try:
                ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                is_tool = bool(ex_style & WS_EX_TOOLWINDOW)
                is_app = bool(ex_style & WS_EX_APPWINDOW)
                if is_tool and not is_app:
                    return 1
                owner = user32.GetWindow(hwnd, GW_OWNER)
                if owner != 0:
                    return 1

                rc = RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rc))
                if rc.right - rc.left <= 0 or rc.bottom - rc.top <= 0:
                    return 1
            except Exception:
                pass

            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pname = "unknown"
            exe_path = ""
            try:
                proc = psutil.Process(pid.value)
                pname = proc.name()
                exe_path = proc.exe()
            except Exception:
                pass

            # Avoid duplicate window handles
            hwnd_str = str(int(hwnd))
            if hwnd_str in seen_hwnds:
                return 1
            seen_hwnds.add(hwnd_str)

            # Determine application category & icon
            target_type, app_name, icon = self._classify_window(title, pname)

            # Extract real native application icon from the Windows executable or window
            icon_data = self._extract_icon_base64(exe_path, int(hwnd))

            target_id = f"win_{hwnd_str}"
            target_obj = Target(
                id=target_id,
                application=app_name,
                window_title=title,
                process_name=pname,
                window_id=hwnd_str,
                target_type=target_type,
                icon=icon,
                icon_data=icon_data,
                exe_path=exe_path or None,
            )
            results.append(target_obj)
            return 1

        try:
            # Query the interactive input desktop for all foreground/visible application windows
            hInput = user32.OpenInputDesktop(0, False, 0x01FF)
            if hInput:
                user32.EnumDesktopWindows(hInput, WNDENUMPROC(enum_proc), 0)
                user32.CloseDesktop(hInput)
            else:
                user32.EnumWindows(WNDENUMPROC(enum_proc), 0)
        except Exception as err:
            logger.error(f"Error enumerating Windows: {err}")

        return results

    def _classify_window(self, title: str, pname: str) -> tuple[TargetType, str, str]:
        pname_upper = pname.upper()
        title_lower = title.lower()

        if "WINWORD" in pname_upper or "word" in title_lower:
            return TargetType.WORD, "Microsoft Word", "file-text"
        elif "EXCEL" in pname_upper or "excel" in title_lower:
            return TargetType.EXCEL, "Microsoft Excel", "table"
        elif any(b in pname_upper for b in ["CHROME", "MSEDGE", "FIREFOX", "BRAVE"]):
            app = "Google Chrome" if "CHROME" in pname_upper else ("Microsoft Edge" if "MSEDGE" in pname_upper else "Browser")
            return TargetType.BROWSER, app, "globe"
        elif "EXPLORER" in pname_upper or "file explorer" in title_lower:
            return TargetType.EXPLORER, "File Explorer", "folder"
        elif "MSPAINT" in pname_upper or "paint" in title_lower:
            return TargetType.PAINT, "Microsoft Paint", "palette"
        elif "ANTIGRAVITY" in pname_upper or "antigravity" in title_lower:
            return TargetType.ANTIGRAVITY, "Antigravity", "sparkles"
        else:
            app_name = pname.split(".")[0].capitalize() if "." in pname else title.split("-")[-1].strip()
            return TargetType.GENERIC, app_name or "Application", "app"

    def get_active_target(self) -> Target:
        if self._active_target_id in self._cached_targets:
            return self._cached_targets[self._active_target_id]
        # Default fallback: Auto / General
        return Target(
            id="auto",
            application="Auto / General",
            window_title="General Search & AI Assistant Mode",
            process_name="none",
            target_type=TargetType.AUTO,
            icon="globe",
        )

    def select_target(self, target_id: str) -> tuple[Target, TargetContext]:
        """Select a new target application/window and lazily acquire its context."""
        targets = self.discover_targets()
        found = next((t for t in targets if t.id == target_id), None)

        if not found:
            # If not in fresh discovery, check cache or build fallback
            found = self._cached_targets.get(target_id)
            if not found:
                raise TargetUnavailableException(f"Target '{target_id}' is no longer available or was closed.")

        self._active_target_id = found.id
        self._cached_targets[found.id] = found

        # Acquire detailed context for the selected target
        context = self.acquire_context(found.id)
        logger.info(f"🎯 Target changed to: {found.application} ({found.window_title})")
        return found, context

    def acquire_context(self, target_id: Optional[str] = None) -> TargetContext:
        tid = target_id or self._active_target_id
        target = self._cached_targets.get(tid) or self.get_active_target()

        now_str = datetime.datetime.now().isoformat()
        details: dict[str, Any] = {}

        if target.target_type == TargetType.ANTIGRAVITY:
            details = self._acquire_antigravity_context()
        elif target.target_type == TargetType.WORD:
            details = self._acquire_word_context(target)
        elif target.target_type == TargetType.EXCEL:
            details = self._acquire_excel_context(target)
        elif target.target_type == TargetType.BROWSER:
            details = self._acquire_browser_context(target)
        else:
            details = {
                "window_handle": target.window_id,
                "process": target.process_name,
                "window_title": target.window_title,
            }

        ctx = TargetContext(
            target_id=target.id,
            application=target.application,
            window_title=target.window_title,
            target_type=target.target_type,
            timestamp=now_str,
            details=details,
        )
        self._active_context = ctx
        return ctx

    def _acquire_antigravity_context(self) -> dict[str, Any]:
        cwd = Path.cwd().resolve()
        return {
            "workspace_root": str(cwd),
            "project_name": cwd.name,
            "environment": "Antigravity IDE",
            "active_workspace": str(cwd),
            "active_files": ["backend/requirements.txt", "backend/main.py"],
        }

    def _acquire_word_context(self, target: Target) -> dict[str, Any]:
        """Acquire detailed Word document context using win32com COM interface for the targeted document."""
        ctx_details: dict[str, Any] = {
            "application": "Microsoft Word",
            "window_title": target.window_title,
        }
        if os.name == "nt":
            try:
                import win32com.client
                word = win32com.client.GetActiveObject("Word.Application")
                if word and word.Documents.Count > 0:
                    doc = None
                    win = None
                    target_hwnd = int(target.window_id) if target.window_id and target.window_id.isdigit() else None
                    target_title_clean = target.window_title.replace(" - Word", "").replace(" Microsoft Word", "").lower().strip()

                    # 1. Match window handle
                    if target_hwnd:
                        for d in word.Documents:
                            try:
                                for w in d.Windows:
                                    if getattr(w, "Hwnd", None) and int(w.Hwnd) == target_hwnd:
                                        doc = d
                                        win = w
                                        break
                            except Exception:
                                pass
                            if doc:
                                break

                    # 2. Match caption / title
                    if not doc:
                        for d in word.Documents:
                            d_name = str(d.Name).lower().strip()
                            d_full = str(getattr(d, "FullName", "")).lower().strip()
                            try:
                                for w in d.Windows:
                                    w_cap = str(getattr(w, "Caption", "")).lower().strip()
                                    w_cap_clean = w_cap.replace(" - word", "").replace(" microsoft word", "").strip()
                                    if w_cap_clean and (w_cap_clean in target_title_clean or target_title_clean in w_cap_clean):
                                        doc = d
                                        win = w
                                        break
                            except Exception:
                                pass
                            if doc:
                                break

                            if d_name and (d_name in target_title_clean or target_title_clean in d_name):
                                doc = d
                                win = d.Windows(1) if d.Windows.Count > 0 else None
                                break
                            if d_full and (d_full in target_title_clean or target_title_clean in d_full):
                                doc = d
                                win = d.Windows(1) if d.Windows.Count > 0 else None
                                break

                    # 3. Fallback for AUTO mode
                    if not doc and target.target_type == TargetType.AUTO:
                        doc = word.ActiveDocument
                        win = word.ActiveWindow

                    if doc:
                        sel = win.Selection if win else word.Selection
                        font = sel.Font
                        para = sel.Paragraphs(1) if sel.Paragraphs.Count > 0 else None

                        selected_text = str(sel.Text).strip("\r\n\x07")
                        current_para_text = str(para.Range.Text).strip("\r\n\x07") if para else ""

                        ctx_details.update({
                            "document_name": doc.Name,
                            "document_path": getattr(doc, "FullName", doc.Name),
                            "paragraph_count": doc.Paragraphs.Count,
                            "selected_text": selected_text,
                            "current_paragraph": current_para_text,
                            "font_name": font.Name,
                            "font_size": font.Size if font.Size != 9999999 else "Mixed",
                            "bold": bool(font.Bold) if font.Bold != 9999999 else "Mixed",
                            "italic": bool(font.Italic) if font.Italic != 9999999 else "Mixed",
                            "alignment": para.Format.Alignment if para else 0,
                            "style": str(sel.Style.NameLocal) if hasattr(sel, "Style") else "Normal",
                            "com_connected": True,
                        })
                        return ctx_details
            except Exception as err:
                logger.debug(f"Word COM context fetch fallback: {err}")

        # Fallback to in-memory DocxAdapter session if available
        try:
            from backend.agent.tools.document.adapter import docx_adapter
            sid = docx_adapter._last_active_session_id
            if sid:
                stats = docx_adapter.read_document(sid)
                ctx_details.update(stats.to_dict())
                ctx_details["session_id"] = sid
        except Exception:
            pass

        return ctx_details

    def _acquire_excel_context(self, target: Target) -> dict[str, Any]:
        """Acquire detailed Excel workbook context using win32com COM interface for the targeted workbook."""
        if os.name == "nt":
            try:
                from backend.agent.tools.excel_copilot.context import acquire_deep_excel_context
                target_hwnd = int(target.window_id) if target.window_id and target.window_id.isdigit() else None
                deep_ctx = acquire_deep_excel_context(workbook_name=target.window_title, hwnd=target_hwnd)
                if deep_ctx:
                    deep_ctx["com_connected"] = True
                    return deep_ctx
            except Exception as err:
                logger.debug(f"Excel deep context error, falling back: {err}")

        return {
            "application": "Microsoft Excel",
            "window_title": target.window_title,
        }

    def _acquire_browser_context(self, target: Target) -> dict[str, Any]:
        """Acquire browser tab context via Chrome Companion Extension Bridge."""
        ctx_details: dict[str, Any] = {
            "application": target.application,
            "window_title": target.window_title,
            "browser_connected": False,
        }
        try:
            from backend.agent.tools.web_automation.extension_bridge import extension_bridge
            if extension_bridge.is_connected():
                ctx_details["browser_connected"] = True
                # If specific tab ID is present, format tab info
                if target.browser_tab_id:
                    ctx_details["tab_id"] = target.browser_tab_id
                if target.browser_url:
                    ctx_details["url"] = target.browser_url
        except Exception as e:
            logger.debug(f"Browser context acquisition error: {e}")

        return ctx_details

    def refresh_current_context(self) -> TargetContext:
        """Refresh current context and verify target window is still alive."""
        target = self.get_active_target()
        if target.target_type != TargetType.ANTIGRAVITY and target.window_id:
            user32 = ctypes.windll.user32
            try:
                hwnd_int = int(target.window_id)
                if not user32.IsWindow(hwnd_int):
                    raise TargetUnavailableException(
                        f"The selected target window '{target.window_title}' is no longer available. Please select another target."
                    )
            except (ValueError, TypeError):
                pass

        return self.acquire_context(target.id)


target_manager = TargetManager.get_instance()
