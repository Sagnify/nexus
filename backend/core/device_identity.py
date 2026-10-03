"""Persistent identity for one NEXUS installation/device profile."""
from __future__ import annotations

import uuid
from pathlib import Path


DEVICE_ID_PATH = Path.home() / ".nexus" / "device_id"


def get_device_id() -> str:
    """Return a stable UUID for this OS user profile's NEXUS installation."""
    DEVICE_ID_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = DEVICE_ID_PATH.read_text(encoding="utf-8").strip()
        return str(uuid.UUID(value))
    except (OSError, ValueError):
        value = str(uuid.uuid4())
        DEVICE_ID_PATH.write_text(value, encoding="utf-8")
        return value
