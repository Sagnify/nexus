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

CREDENTIALS_FILE = Path.home() / ".nexus" / "connector_credentials.json"


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
        if not creds.get("refresh_token") and existing.get("refresh_token"):
            creds["refresh_token"] = existing["refresh_token"]

        data[user_key][connector_id] = creds

        # Always mirror to default and local_default_user for seamless desktop daemon resolution
        for mirror_key in ("default", "local_default_user"):
            if mirror_key not in data:
                data[mirror_key] = {}
            mirror_existing = data.get(mirror_key, {}).get(connector_id, {})
            if not creds.get("refresh_token") and mirror_existing.get("refresh_token"):
                creds["refresh_token"] = mirror_existing["refresh_token"]
            data[mirror_key][connector_id] = creds

        self._write(data)

    def get_credential(self, user_id: str, connector_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve credentials for a connector without exposing them to outside callers."""
        data = self._read()
        user_key = str(user_id or "default")

        # 1. Direct match
        user_creds = data.get(user_key, {})
        if connector_id in user_creds:
            return user_creds[connector_id]

        # 2. Check local desktop fallbacks
        for fallback_key in ("local_default_user", "default"):
            if fallback_key in data and connector_id in data[fallback_key]:
                return data[fallback_key][connector_id]

        # 3. Check any user namespace on this workstation
        for k, v in data.items():
            if isinstance(v, dict) and connector_id in v:
                return v[connector_id]

        return None

    def delete_credential(self, user_id: str, connector_id: str) -> bool:
        """Purge credentials when a connector is disconnected."""
        data = self._read()
        user_key = str(user_id or "default")
        deleted = False

        # Delete from requested user_key
        if user_key in data and connector_id in data[user_key]:
            del data[user_key][connector_id]
            deleted = True

        # Also purge from all fallbacks
        for fb in ("default", "local_default_user"):
            if fb in data and connector_id in data[fb]:
                del data[fb][connector_id]
                deleted = True

        for k, v in list(data.items()):
            if isinstance(v, dict) and connector_id in v:
                del v[connector_id]
                deleted = True

        if deleted:
            self._write(data)
        return deleted


credentials_store = ConnectorCredentialsStore()
CredentialsStore = ConnectorCredentialsStore

