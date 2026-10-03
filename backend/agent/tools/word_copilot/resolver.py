"""Target resolver for Microsoft Word windows and documents.

Ensures that the floating NEXUS assistant binds to the exact targeted Word window
and document, preventing cross-document mutations when multiple documents are open.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nexus.word_copilot.resolver")


class WordTargetError(Exception):
    """Raised when the specified Word target cannot be resolved or accessed."""
    pass


def get_word_app_from_hwnd(hwnd: int) -> Optional[Any]:
    """Retrieve the Word.Application COM object from an OpusApp or _WwG window handle via oleacc."""
    if not hwnd or os.name != "nt":
        return None
    try:
        import ctypes
        import win32gui
        import pythoncom
        import win32com.client

        wwg_hwnds: List[int] = []

        def _enum_child(h: int, _: Any) -> bool:
            try:
                if win32gui.GetClassName(h) == "_WwG":
                    wwg_hwnds.append(h)
                    return False
            except Exception:
                pass
            return True

        try:
            if win32gui.GetClassName(hwnd) == "_WwG":
                wwg_hwnds.append(hwnd)
            else:
                win32gui.EnumChildWindows(hwnd, _enum_child, None)
        except Exception:
            pass

        if not wwg_hwnds:
            # Fallback: try GetActiveObject directly
            try:
                return win32com.client.GetActiveObject("Word.Application")
            except Exception:
                return None

        oleacc = ctypes.windll.oleacc
        IID_IDispatch = pythoncom.IID_IDispatch
        OBJID_NATIVEOM = 0xFFFFFFF0

        class GUID(ctypes.Structure):
            _fields_ = [
                ('Data1', ctypes.c_ulong),
                ('Data2', ctypes.c_ushort),
                ('Data3', ctypes.c_ushort),
                ('Data4', ctypes.c_ubyte * 8)
            ]

        guid = GUID(0x00020400, 0x0000, 0x0000, (ctypes.c_ubyte * 8)(0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46))
        ptr = ctypes.c_void_p()

        res = oleacc.AccessibleObjectFromWindow(
            wwg_hwnds[0],
            ctypes.c_uint32(OBJID_NATIVEOM),
            ctypes.byref(guid),
            ctypes.byref(ptr)
        )
        if res == 0 and ptr.value:
            disp = win32com.client.Dispatch(pythoncom.ObjectFromAddress(ptr.value, IID_IDispatch))
            if hasattr(disp, "Application"):
                return disp.Application
    except Exception as exc:
        logger.debug(f"Could not get Word app from hwnd {hwnd}: {exc}")
    return None


def is_window_or_process_foreground(
    target_hwnd: int,
    allowed_hwnds: Optional[set[int]] = None,
    electron_pid: Optional[int] = None,
) -> bool:
    """
    Check if target_hwnd or its process is the active foreground window,
    OR if the user is interacting with the Electron copilot pill window.
    """
    if not target_hwnd or os.name != "nt":
        return False
    try:
        import win32gui
        import win32process

        fg = win32gui.GetForegroundWindow()
        if not fg:
            return False

        # 1. Direct HWND match (Word top-level OpusApp window)
        if fg == target_hwnd:
            return True

        # 2. Child/Ancestor match (document surface _WwG, ribbon, modal dialog in Word)
        root_fg = win32gui.GetAncestor(fg, 2)  # GA_ROOT
        if root_fg == target_hwnd:
            return True

        _, fg_pid = win32process.GetWindowThreadProcessId(fg)
        _, target_pid = win32process.GetWindowThreadProcessId(target_hwnd)

        # 3. Process ID match: foreground window belongs to the Word process
        if fg_pid > 0 and target_pid > 0 and fg_pid == target_pid:
            return True

        # 4. User is interacting with the Electron copilot pill itself
        if electron_pid and fg_pid > 0 and fg_pid == electron_pid:
            return True

        # 5. Direct HWND match with copilot windows
        if allowed_hwnds and (fg in allowed_hwnds or root_fg in allowed_hwnds):
            return True

        # Any other app (Chrome, VSCode, File Explorer, Desktop, Notepad, etc.) is foreground
        return False
    except Exception:
        return False


def get_open_word_windows(
    copilot_hwnds: Optional[set[int]] = None,
    electron_pid: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Enumerate all open Word documents and windows with their HWNDs, titles, and foreground state."""
    if os.name != "nt":
        return []

    windows_info = []
    try:
        import win32gui

        # Enumerate visible OpusApp windows (Word main window class)
        opus_hwnds: List[int] = []

        def _find_opus(h: int, _: Any) -> bool:
            try:
                if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h) == "OpusApp":
                    opus_hwnds.append(h)
            except Exception:
                pass
            return True

        try:
            win32gui.EnumWindows(_find_opus, None)
        except Exception:
            pass

        if not opus_hwnds:
            return []

        for h in opus_hwnds:
            try:
                r = win32gui.GetWindowRect(h)
                is_minimized = bool(win32gui.IsIconic(h))
                # Strictly evaluate foreground state without blocking COM calls
                is_fg = (
                    not is_minimized
                    and is_window_or_process_foreground(
                        int(h),
                        allowed_hwnds=copilot_hwnds,
                        electron_pid=electron_pid,
                    )
                )
                title = win32gui.GetWindowText(h)
                doc_name = (
                    title.replace(" - Word", "")
                    .replace(" - Microsoft Word", "")
                    .strip()
                    or "Document1"
                )

                windows_info.append({
                    "hwnd": int(h),
                    "title": f"{doc_name} - Word" if "Word" not in title else title,
                    "document_name": doc_name,
                    "document_path": doc_name,
                    "visible": not is_minimized and bool(win32gui.IsWindowVisible(h)),
                    "is_minimized": is_minimized,
                    "is_foreground": is_fg,
                    "rect": {
                        "left": r[0],
                        "top": r[1],
                        "right": r[2],
                        "bottom": r[3],
                        "width": max(0, r[2] - r[0]),
                        "height": max(0, r[3] - r[1]),
                    },
                })
            except Exception as err:
                logger.debug(f"Error enumerating OpusApp window {h}: {err}")

        return windows_info
    except Exception as exc:
        logger.warning(f"Error retrieving open Word windows: {exc}")
        return []


def resolve_word_target(
    document_name: Optional[str] = None,
    hwnd: Optional[int] = None,
    target_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[Any, Any, Any]:
    """
    Resolve and bind to the specific Word Application, Document, and Window.
    Returns: (word_app, document, active_window)
    Raises WordTargetError if target cannot be found or accessed.
    """
    if os.name != "nt":
        raise WordTargetError("Microsoft Word COM automation is only available on Windows.")

    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass

    import win32com.client

    # 1. Try to obtain COM application from specific HWND first
    word_app = None
    if hwnd:
        word_app = get_word_app_from_hwnd(hwnd)

    # 2. Fall back to GetActiveObject
    if not word_app:
        try:
            word_app = win32com.client.GetActiveObject("Word.Application")
        except Exception:
            pass

    # 3. Fall back to Dispatch
    if not word_app:
        try:
            word_app = win32com.client.Dispatch("Word.Application")
        except Exception as e:
            raise WordTargetError(f"Cannot connect to Microsoft Word: {e}")

    if not word_app or not hasattr(word_app, "Documents"):
        raise WordTargetError("Connected to Word COM, but Documents collection is unavailable.")

    if len(word_app.Documents) == 0:
        raise WordTargetError("No open documents found in Microsoft Word.")

    # 4. Resolve exact Document
    target_doc = None
    clean_target_name = (document_name or "").strip().lower()

    if clean_target_name:
        for d in word_app.Documents:
            d_name = str(d.Name).lower()
            if d_name == clean_target_name or d_name.startswith(clean_target_name):
                target_doc = d
                break

    if not target_doc and hasattr(word_app, "ActiveDocument") and word_app.ActiveDocument:
        target_doc = word_app.ActiveDocument

    if not target_doc:
        target_doc = word_app.Documents[0]

    win = getattr(word_app, "ActiveWindow", None)
    return word_app, target_doc, win
