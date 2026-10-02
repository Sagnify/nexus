"""Persistent local settings store — saves to ~/.nexus/settings.json."""
from __future__ import annotations
import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".nexus" / "settings.json"

_DEFAULTS: dict = {
    "groq_api_key": "",
    "gemma_api_key": "",
    "groq_fast_model": "openai/gpt-oss-20b",
    "groq_reasoning_model": "openai/gpt-oss-20b",
    "groq_vision_model": "llama-3.2-11b-vision-preview",
    "groq_tool_model": "openai/gpt-oss-20b",
    "postgres_url": "",
    "embedding_model": "all-minilm",
    "voice_input_enabled": True,
    "voice_wake_word_enabled": True,
    "voice_auto_submit": True,
    "voice_output_enabled": True,
    "voice_output_voice": "en-US-AriaNeural",
    "voice_output_speed": "1.0x",
}

# Secrets that should be masked when returned to the frontend
_SECRET_KEYS = {"groq_api_key", "gemma_api_key", "postgres_url"}


class SettingsStore:
    def __init__(self, path: Path = SETTINGS_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write(_DEFAULTS.copy())

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text())
            merged = {**_DEFAULTS, **data}
            # Auto-sanitize genuinely decommissioned or low-quota models
            decommissioned = (
                "gemma2", "gemma-7b", "gemma-9b",
                "mixtral-8x7b", "mixtral-8x22b",
                "llama2", "codellama", "compound",
                "llama-3.1-8b-instant", "llama-3.2-8b",
            )
            dirty = False
            model_defaults = {
                "groq_fast_model": "openai/gpt-oss-20b",
                "groq_reasoning_model": "openai/gpt-oss-20b",
                "groq_vision_model": "llama-3.2-11b-vision-preview",
                "groq_tool_model": "openai/gpt-oss-20b",
            }
            # Also migrate qwen models in fast/tool roles to prevent 1000 OTPM rate-limiting
            for k in ("groq_fast_model", "groq_tool_model"):
                val = str(merged.get(k, "")).lower()
                if "qwen" in val:
                    merged[k] = "openai/gpt-oss-20b"
                    dirty = True

            for k, fallback in model_defaults.items():
                val = str(merged.get(k, "")).lower()
                if not val or any(d in val for d in decommissioned):
                    merged[k] = fallback
                    dirty = True
            if dirty:
                self._write(merged)
            return merged
        except Exception:
            return _DEFAULTS.copy()

    def save(self, data: dict) -> dict:
        current = self.load()
        # Merge — empty strings or masked placeholders from frontend = don't overwrite existing secret
        for key, value in data.items():
            if key in _SECRET_KEYS:
                if value in ("", None):
                    continue  # Don't overwrite existing secret with empty
                if isinstance(value, str) and ("•" in value or "\u2022" in value or "*" in value):
                    continue  # Masked value from frontend, preserve existing real secret
            current[key] = value
        self._write(current)
        return current

    def masked(self) -> dict:
        """Return settings with secrets partially masked for the frontend."""
        data = self.load()
        result = {}
        for k, v in data.items():
            if k in _SECRET_KEYS and v:
                result[k] = v[:4] + "•" * max(0, len(v) - 8) + v[-4:] if len(v) > 8 else "••••••••"
            else:
                result[k] = v
        return result

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2))
