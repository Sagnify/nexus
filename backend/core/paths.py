"""
Dynamic user and system paths resolution for Windows & multi-platform environments.
Accurately detects OneDrive-redirected folders (Desktop, Documents, Pictures, Downloads)
via Windows Registry & Shell Known Folders APIs so that file operations,
spreadsheets, documents, and downloads always resolve to the user's active desktop
regardless of whether OneDrive, OneDrive for Business, or standard local folders are used.
"""

import os
import re
import sys
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger("nexus.paths")


def get_active_desktop() -> Path:
    """Accurately find user's active Desktop folder, respecting OneDrive and Windows Shell redirection."""
    if sys.platform == "win32":
        # 1. Query Windows Registry User Shell Folders (Primary ground truth for redirected folders)
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            val, _ = winreg.QueryValueEx(key, "Desktop")
            winreg.CloseKey(key)
            expanded = os.path.expandvars(val)
            p = Path(expanded)
            if p.exists() and p.is_dir():
                return p
        except Exception as e:
            logger.debug(f"Registry query for Desktop failed: {e}")

        # 2. Check OneDrive Desktop folder variants
        try:
            home = Path.home()
            for od_dir in home.glob("OneDrive*"):
                if od_dir.is_dir():
                    candidate = od_dir / "Desktop"
                    if candidate.exists() and candidate.is_dir():
                        return candidate
        except Exception:
            pass

    # 3. Standard fallback: ~/Desktop
    std_desktop = Path.home() / "Desktop"
    if not std_desktop.exists():
        try:
            std_desktop.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return std_desktop


def get_active_documents() -> Path:
    """Accurately find user's active Documents folder, respecting OneDrive redirection."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            val, _ = winreg.QueryValueEx(key, "Personal")
            winreg.CloseKey(key)
            expanded = os.path.expandvars(val)
            p = Path(expanded)
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass

        try:
            home = Path.home()
            for od_dir in home.glob("OneDrive*"):
                if od_dir.is_dir():
                    candidate = od_dir / "Documents"
                    if candidate.exists() and candidate.is_dir():
                        return candidate
        except Exception:
            pass

    return Path.home() / "Documents"


def get_active_downloads() -> Path:
    """Find user's Downloads folder."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            val, _ = winreg.QueryValueEx(key, "{374DE290-123F-4565-9164-39C4925E467B}")
            winreg.CloseKey(key)
            expanded = os.path.expandvars(val)
            p = Path(expanded)
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass
    return Path.home() / "Downloads"


def get_active_pictures() -> Path:
    """Find user's Pictures folder, respecting OneDrive redirection."""
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            )
            val, _ = winreg.QueryValueEx(key, "My Pictures")
            winreg.CloseKey(key)
            expanded = os.path.expandvars(val)
            p = Path(expanded)
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass
    return Path.home() / "Pictures"


def resolve_system_path(raw_path: str | Path, default_filename: str = "file") -> Path:
    """
    Resolve any file or directory path dynamically:
    - Handles tildes (~), env vars (%USERPROFILE%, $HOME)
    - Strips quotes
    - Redirects shortcut prefixes ('desktop/file.xlsx', 'Desktop', 'documents/...') to the active OneDrive/Shell folders
    - Redirects hardcoded local paths (e.g. 'C:\\Users\\user\\Desktop\\file.xlsx') to the active OneDrive Desktop if redirected
    - If a bare filename without directory is given, defaults to user's active Desktop
    """
    raw_str = str(raw_path).strip().strip("\"'")

    # Sanitize literal placeholder tokens like <username> or <user>
    raw_str = re.sub(r"[a-zA-Z]:[/\\]Users[/\\]<[^>]+>", lambda _: str(Path.home()), raw_str, flags=re.IGNORECASE)
    raw_str = re.sub(r"<username>|<user>", lambda _: Path.home().name, raw_str, flags=re.IGNORECASE)

    expanded = os.path.expandvars(os.path.expanduser(raw_str))
    clean = expanded.replace("\\", "/")
    lower = clean.lower()

    active_desktop = get_active_desktop()
    active_documents = get_active_documents()
    active_downloads = get_active_downloads()

    # 1. Check relative shortcuts: 'desktop', 'desktop/...'
    if lower.startswith("desktop/") or lower == "desktop":
        sub = clean[8:].lstrip("/") if len(clean) > 7 else ""
        target = active_desktop / sub if sub else (active_desktop / default_filename)
        return target.resolve()

    if lower.startswith("documents/") or lower == "documents":
        sub = clean[10:].lstrip("/") if len(clean) > 9 else ""
        target = active_documents / sub if sub else (active_documents / default_filename)
        return target.resolve()

    if lower.startswith("downloads/") or lower == "downloads":
        sub = clean[10:].lstrip("/") if len(clean) > 9 else ""
        target = active_downloads / sub if sub else (active_downloads / default_filename)
        return target.resolve()

    # 2. Redirect hardcoded/standard local Desktop prefix -> active (OneDrive) Desktop
    std_desktop_prefix = str(Path.home() / "Desktop").replace("\\", "/").lower()
    if clean.lower().startswith(std_desktop_prefix):
        sub = clean[len(std_desktop_prefix):].lstrip("/")
        target = active_desktop / sub if sub else (active_desktop / default_filename)
        return target.resolve()

    # 3. Redirect hardcoded/standard local Documents prefix -> active (OneDrive) Documents
    std_docs_prefix = str(Path.home() / "Documents").replace("\\", "/").lower()
    if clean.lower().startswith(std_docs_prefix):
        sub = clean[len(std_docs_prefix):].lstrip("/")
        target = active_documents / sub if sub else (active_documents / default_filename)
        return target.resolve()

    # 4. If path is a bare filename without any directory, save to active Desktop by default
    p = Path(expanded)
    if not p.is_absolute() and len(p.parts) <= 1:
        return (active_desktop / p.name).resolve()

    # 5. General relative path
    if not p.is_absolute():
        p = Path.cwd() / p

    return p.resolve()
