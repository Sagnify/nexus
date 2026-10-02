"""Settings API endpoints."""
from __future__ import annotations
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

from backend.core.settings_store import SettingsStore
from backend.agent.router.registry import registry

router = APIRouter()
_store = SettingsStore()


class SettingsUpdate(BaseModel):
    groq_api_key: Optional[str] = None
    gemma_api_key: Optional[str] = None
    groq_fast_model: Optional[str] = None
    groq_reasoning_model: Optional[str] = None
    groq_vision_model: Optional[str] = None
    groq_tool_model: Optional[str] = None
    postgres_url: Optional[str] = None
    embedding_model: Optional[str] = None
    voice_input_enabled: Optional[bool] = None
    voice_wake_word_enabled: Optional[bool] = None
    voice_auto_submit: Optional[bool] = None


@router.get("")
async def get_settings():
    return _store.masked()


@router.post("")
async def save_settings(payload: SettingsUpdate):
    data = payload.model_dump(exclude_unset=True)
    updated = _store.save(data)
    return {
        "status": "saved",
        "settings": _store.masked()
    }


@router.get("/models")
async def get_available_models():
    return [
        {
            "name": p.name,
            "model_id": p.model_id,
            "context_window": p.context_window,
            "speed": p.speed,
            "reasoning": p.reasoning,
            "tool_calling": p.tool_calling,
            "vision": p.vision,
        }
        for p in registry.all()
    ]
