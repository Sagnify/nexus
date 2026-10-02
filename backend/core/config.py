"""NEXUS configuration — reads from settings store and environment."""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from backend.core.settings_store import SettingsStore

# Load environment variables from .env file
load_dotenv()

_store = SettingsStore()


def get_settings() -> dict:
    return _store.load()


def get_groq_api_key() -> str | None:
    # Interface user settings (~/.nexus/settings.json) takes highest priority
    key = get_settings().get("groq_api_key")
    if key and isinstance(key, str):
        key = key.strip()
        if not ("•" in key or "\u2022" in key or "*" in key):
            if not (key.startswith("gsk_your") or key == "your_groq_api_key_here" or "placeholder" in key.lower()):
                try:
                    key.encode("ascii")
                    if key:
                        return key
                except UnicodeEncodeError:
                    pass

    # .env fallback for developer convenience only
    env_key = os.getenv("GROQ_API_KEY", "")
    if env_key and isinstance(env_key, str):
        env_key = env_key.strip()
        if not ("•" in env_key or "\u2022" in env_key or "*" in env_key):
            if not (env_key.startswith("gsk_your") or env_key == "your_groq_api_key_here" or "placeholder" in env_key.lower()):
                try:
                    env_key.encode("ascii")
                    return env_key if env_key else None
                except UnicodeEncodeError:
                    pass
    return None


def get_gemma_api_key() -> str | None:
    # Interface user settings takes highest priority
    key = get_settings().get("gemma_api_key")
    if key and isinstance(key, str):
        key = key.strip()
        if not ("•" in key or "\u2022" in key or "*" in key):
            if not ("placeholder" in key.lower() or key.startswith("your_")):
                try:
                    key.encode("ascii")
                    if key:
                        return key
                except UnicodeEncodeError:
                    pass

    # .env fallback
    env_key = os.getenv("GEMMA_API_KEY", "")
    if env_key and isinstance(env_key, str):
        env_key = env_key.strip()
        if not ("•" in env_key or "\u2022" in env_key or "*" in env_key):
            if not ("placeholder" in env_key.lower() or env_key.startswith("your_")):
                try:
                    env_key.encode("ascii")
                    return env_key if env_key else None
                except UnicodeEncodeError:
                    pass
    return None


def get_spotify_client_id() -> str | None:
    """Return the public Spotify OAuth client ID from settings or environment."""
    client_id = get_settings().get("spotify_client_id") or os.getenv("SPOTIFY_CLIENT_ID", "")
    if not isinstance(client_id, str):
        return None
    client_id = client_id.strip()
    return client_id or None


# Real Groq Chat Completion API model IDs used as defaults.
# Verified available on the active Groq account.
_GROQ_MODEL_DEFAULTS = {
    "fast": "openai/gpt-oss-20b",        # Fast single-step LPU inference (high OTPM headroom)
    "reasoning": "openai/gpt-oss-20b",   # Reasoning model
    "vision": "llama-3.2-11b-vision-preview",  # Vision-capable model
    "tool": "openai/gpt-oss-20b",        # Tool/function calling
}

# Model IDs that are no longer valid or non-existent on this Groq tier.
_DECOMMISSIONED_FRAGMENTS = (
    "gemma2", "gemma-7b", "gemma-9b",
    "mixtral-8x7b", "mixtral-8x22b",
    "llama2", "codellama", "compound",
    "llama-3.1-8b-instant", "llama-3.2-8b",
)


def get_groq_model(capability: str = "reasoning") -> str:
    """Return the configured Groq Chat Completion model ID for the given capability.

    Priority: interface user settings > env var > hardcoded default.
    Any model matching a decommissioned fragment is replaced with the default.
    """
    env_map = {
        "fast": "GROQ_FAST_MODEL",
        "reasoning": "GROQ_REASONING_MODEL",
        "vision": "GROQ_VISION_MODEL",
        "tool": "GROQ_TOOL_MODEL",
    }
    settings = get_settings()
    settings_map = {
        "fast": settings.get("groq_fast_model"),
        "reasoning": settings.get("groq_reasoning_model"),
        "vision": settings.get("groq_vision_model"),
        "tool": settings.get("groq_tool_model"),
    }

    default = _GROQ_MODEL_DEFAULTS.get(capability, _GROQ_MODEL_DEFAULTS["reasoning"])

    # 1. Interface user settings takes highest priority
    model = (settings_map.get(capability) or "").strip() or None
    # 2. Check environment variable fallback
    if not model:
        model = os.getenv(env_map.get(capability, ""), "").strip() or None
    # 3. Use hardcoded default
    if not model:
        model = default

    # Strip "groq/" prefix if the user typed it (Groq API doesn't want it)
    if model.startswith("groq/"):
        model = model[len("groq/"):]

    # Replace any decommissioned / invalid model with the capability default
    model_lower = model.lower()
    if any(frag in model_lower for frag in _DECOMMISSIONED_FRAGMENTS):
        model = default

    return model


def get_postgres_url() -> str | None:
    return os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or get_settings().get("postgres_url")

