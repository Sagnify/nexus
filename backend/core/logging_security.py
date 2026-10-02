"""Redact credentials from application and HTTP client log messages."""
from __future__ import annotations

import logging
import re


_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)([?&](?:key|api[_-]?key|access[_-]?token|refresh[_-]?token|token|client[_-]?secret|password|authorization)=)[^&\s\"'<>]+"
)
_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)\b((?:groq|gemma|google|spotify)?[_-]?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|password))\s*[:=]\s*[^\s,;\"']+"
)
_BEARER_VALUE = re.compile(r"(?i)\bBearer\s+[^\s,;\"']+")


def redact_secrets(message: str) -> str:
    """Remove common credential values from URLs, assignments, and auth headers."""
    message = _SENSITIVE_QUERY_VALUE.sub(r"\1[REDACTED]", message)
    message = _SENSITIVE_ASSIGNMENT.sub(r"\1=[REDACTED]", message)
    return _BEARER_VALUE.sub("Bearer [REDACTED]", message)


class SecretRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact_secrets(record.getMessage())
            record.args = ()
        except Exception:
            record.msg = "[REDACTED LOG MESSAGE]"
            record.args = ()
        return True


def install_secret_redaction() -> None:
    """Install redaction on root handlers so propagated library logs are covered."""
    redactor = SecretRedactionFilter()
    root = logging.getLogger()
    for handler in root.handlers:
        if not any(isinstance(item, SecretRedactionFilter) for item in handler.filters):
            handler.addFilter(redactor)