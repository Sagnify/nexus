"""Automated installer and registry configuration for NEXUS Chrome Companion Extension."""
from __future__ import annotations
import os
import sys
import json
import logging
from pathlib import Path

logger = logging.getLogger("nexus.extension_installer")

EXTENSION_DIR = Path(__file__).resolve().parent.parent.parent / "extension"
NATIVE_HOST_NAME = "com.nexus.agent"


def get_extension_path() -> Path:
    return EXTENSION_DIR


def ensure_installed() -> bool:
    """Ensure extension files exist and write Native Messaging Host manifest for Windows."""
    try:
        manifest_file = EXTENSION_DIR / "manifest.json"
        if not manifest_file.exists():
            logger.warning(f"Extension directory not found at {EXTENSION_DIR}")
            return False

        if sys.platform == "win32":
            _register_windows_native_host()
            _purge_legacy_shortcuts()

        return True
    except Exception as e:
        logger.debug(f"Could not auto-register extension: {e}")
        return False


def _purge_legacy_shortcuts():
    """Remove any legacy Google Chrome (NEXUS) shortcuts created on Desktop."""
    try:
        desktop_paths = [
            Path.home() / "Desktop",
            Path.home() / "OneDrive" / "Desktop",
        ]
        for dp in desktop_paths:
            lnk = dp / "Google Chrome (NEXUS).lnk"
            if lnk.exists():
                lnk.unlink(missing_ok=True)
                logger.info(f"Purged legacy shortcut at {lnk}")
    except Exception as e:
        logger.debug(f"Legacy shortcut cleanup ignored: {e}")



def _register_windows_native_host():
    """Register native messaging host in Windows HKCU registry."""
    try:
        import winreg

        host_dir = Path.home() / ".nexus" / "native_host"
        host_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = host_dir / f"{NATIVE_HOST_NAME}.json"

        manifest_content = {
            "name": NATIVE_HOST_NAME,
            "description": "NEXUS Agent Native Messaging Host",
            "path": sys.executable,
            "type": "stdio",
            "allowed_origins": [
                f"chrome-extension://*/"
            ]
        }
        manifest_path.write_text(json.dumps(manifest_content, indent=2), encoding="utf-8")

        # Write to Windows Registry for Chrome and Edge
        for browser in ("Google\\Chrome", "Microsoft\\Edge"):
            key_path = f"Software\\{browser}\\NativeMessagingHosts\\{NATIVE_HOST_NAME}"
            try:
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
            except Exception as e:
                logger.debug(f"Could not write registry key for {browser}: {e}")

        # Configure Chrome Extension Developer Policies
        _configure_chrome_policies()

    except Exception as exc:
        logger.debug(f"Windows native host registration error: {exc}")


def _configure_chrome_policies():
    """Add extension folder to Chrome trusted developer install sources."""
    try:
        import winreg
        policy_path = r"Software\Policies\Google\Chrome\ExtensionInstallSources"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, policy_path) as key:
            winreg.SetValueEx(key, "1", 0, winreg.REG_SZ, f"file:///{str(EXTENSION_DIR).replace(chr(92), '/')}/*")
    except Exception as e:
        logger.debug(f"Policy write ignored: {e}")

