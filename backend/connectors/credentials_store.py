"""
Secure Local Credentials Store for Connectors.
Stores OAuth tokens, API keys, and connector secrets securely in ~/.nexus/connector_credentials.json.
Secrets are never returned in public API payloads.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nexus.connectors.credentials")

from backend.core.device_identity import get_device_id
import uuid

CREDENTIALS_FILE = Path.home() / ".nexus" / "connector_credentials.json"
_dev_id = get_device_id()
_dev_user_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"nexus-local-device-{_dev_id}"))

_LOCAL_USER_KEYS = {
    "default",
    "local_default_user",
    "00000000-0000-0000-0000-000000000001",
    f"local_device_{_dev_id}",
    _dev_user_id,
}


class ConnectorCredentialsStore:
    def __init__(self, file_path: Path = CREDENTIALS_FILE):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists():
            self._write({})

    def _read(self) -> Dict[str, Any]:
        try:
            if not self.file_path.exists():
                return {}
            content = self.file_path.read_text(encoding="utf-8")
            return json.loads(content) if content else {}
        except Exception as e:
            logger.warning(f"Error reading connector credentials: {e}")
            return {}

    def _write(self, data: Dict[str, Any]) -> None:
        try:
            self.file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Error writing connector credentials: {e}")

    def save_credential(self, user_id: str, connector_id: str, creds: Dict[str, Any]) -> None:
        """Store credentials for a connector associated with a user."""
        data = self._read()
        user_key = str(user_id or "default")
        if user_key not in data:
            data[user_key] = {}

        # Preserve existing refresh_token if new payload does not contain one
        existing = data.get(user_key, {}).get(connector_id, {})
        stored_creds = dict(creds)
        if not stored_creds.get("refresh_token") and existing.get("refresh_token"):
            stored_creds["refresh_token"] = existing["refresh_token"]

        data[user_key][connector_id] = stored_creds

        self._write(data)

    def get_credential(self, user_id: str, connector_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve credentials for a connector without exposing them to outside callers."""
        data = self._read()
        user_key = str(user_id or "default")

        # 1. Direct match
        user_creds = data.get(user_key, {})
        if connector_id in user_creds:
            return user_creds[connector_id]

        # Local/guest aliases are one installation identity. Never fall back
        # from an authenticated user to another user's credential namespace.
        if user_key in _LOCAL_USER_KEYS:
            for local_key in _LOCAL_USER_KEYS:
                if connector_id in data.get(local_key, {}):
                    return data[local_key][connector_id]

        return None

    def has_user_credentials(self, user_id: str, connector_id: str) -> bool:
        """Check one exact account namespace without local-alias fallback."""
        data = self._read()
        return connector_id in data.get(str(user_id or "default"), {})

    def migrate_user_credentials(self, source_user_id: str, target_user_id: str) -> bool:
        """Move credentials between two IDs only when auth resolved them to the same account."""
        source_key = str(source_user_id or "")
        target_key = str(target_user_id or "")
        if not source_key or not target_key or source_key == target_key:
            return False

        data = self._read()
        source = data.pop(source_key, None)
        if not isinstance(source, dict):
            return False

        target = data.setdefault(target_key, {})
        for connector_id, credentials in source.items():
            target.setdefault(connector_id, credentials)
        self._write(data)
        return True

    def delete_credential(self, user_id: str, connector_id: str) -> bool:
        """Purge credentials when a connector is disconnected."""
        data = self._read()
        user_key = str(user_id or "default")
        deleted = False

        keys_to_delete = _LOCAL_USER_KEYS if user_key in _LOCAL_USER_KEYS else {user_key}
        for key in keys_to_delete:
            if connector_id in data.get(key, {}):
                del data[key][connector_id]
                deleted = True

        if deleted:
            self._write(data)
        return deleted


credentials_store = ConnectorCredentialsStore()
CredentialsStore = ConnectorCredentialsStore

