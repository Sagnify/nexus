"""Conservative classification for Gmail read, send, and draft requests."""
from __future__ import annotations

import re


def classify_email_request(text: str) -> str:
    lower = (text or "").lower()
    if not re.search(r"\b(?:email|emails|e-mail|e-mails|mail|inbox|message|messages)\b", lower):
        return "unrelated"

    is_read = bool(re.search(
        r"\b(?:check|read|show|list|get|fetch|review|summarize|summary|brief|digest|overview|recap|search|find|view)\b",
        lower,
    ))
    is_send = bool(re.search(r"\bsend\b", lower))
    is_draft = bool(re.search(r"\b(?:draft|compose|write)\b", lower))

    if is_read and (is_send or is_draft):
        return "clarify"
    if is_read:
        return "read"
    if is_send:
        return "send"
    if is_draft:
        return "draft"
    return "clarify"