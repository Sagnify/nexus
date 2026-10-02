"""
Notification Service for N.E.X.U.S.
Delivers notifications to the user via in-app broadcasts, Windows desktop toasts,
and voice synthesis when applicable.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import subprocess
from typing import Optional

logger = logging.getLogger("nexus.notifications")


def show_windows_toast(title: str, message: str) -> None:
    """Display a native Windows notification banner using PowerShell."""
    if sys.platform != "win32":
        return

    # Escape quotes for PowerShell string literal
    safe_title = title.replace('"', '`"').replace("'", "''")
    safe_message = message.replace('"', '`"').replace("'", "''")

    ps_script = f"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName("text")
$textNodes.Item(0).AppendChild($template.CreateTextNode('{safe_title}')) | Out-Null
$textNodes.Item(1).AppendChild($template.CreateTextNode('{safe_message}')) | Out-Null
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("N.E.X.U.S.")
$notification = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier.Show($notification)
"""
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.debug("Failed to display PowerShell toast: %s", exc)


async def send_user_notification(
    title: str,
    message: str,
    notification_type: str = "reminder",
    task_id: Optional[str] = None,
    speak: bool = False,
) -> None:
    """
    Broadcasts a notification to the desktop, active web clients, and optionally speaks it.
    """
    logger.info("[Notification] %s: %s (%s)", title, message, notification_type)

    # 1. Native Windows Toast
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, show_windows_toast, title, message)
    except Exception as exc:
        logger.debug("Desktop toast delivery error: %s", exc)

    # 2. In-app SSE stream broadcast
    try:
        from backend.api.nexus import push_event
        await push_event(
            task_id,
            "scheduled_notification",
            {
                "title": title,
                "message": message,
                "type": notification_type,
                "timestamp": asyncio.get_event_loop().time(),
            },
        )
    except Exception as exc:
        logger.debug("SSE notification broadcast error: %s", exc)

