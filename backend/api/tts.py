"""
Cloud-based Neural Text-to-Speech (TTS) module for Nexus.
Utilizes Microsoft's cloud neural voice service (via edge-tts) for ultra-realistic,
emotive, human-conversational voice synthesis with zero API keys required.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

logger = logging.getLogger("nexus.tts")

router = APIRouter(prefix="/tts", tags=["tts"])

# Curated list of high-quality human conversational neural voices
CURATED_VOICES = [
    {
        "id": "en-US-AriaNeural",
        "name": "Aria",
        "gender": "Female",
        "locale": "en-US",
        "style": "Warm, expressive & conversational (Default)",
    },
    {
        "id": "en-US-GuyNeural",
        "name": "Guy",
        "gender": "Male",
        "locale": "en-US",
        "style": "Relaxed, clear & natural",
    },
    {
        "id": "en-US-JennyMultilingualNeural",
        "name": "Jenny",
        "gender": "Female",
        "locale": "en-US",
        "style": "Friendly, modern & versatile",
    },
    {
        "id": "en-US-ChristopherNeural",
        "name": "Christopher",
        "gender": "Male",
        "locale": "en-US",
        "style": "Authoritative & confident",
    },
    {
        "id": "en-GB-SoniaNeural",
        "name": "Sonia",
        "gender": "Female",
        "locale": "en-GB",
        "style": "Warm British conversational",
    },
    {
        "id": "en-GB-BrianNeural",
        "name": "Brian",
        "gender": "Male",
        "locale": "en-GB",
        "style": "Natural British conversational",
    },
    {
        "id": "en-IN-NeerjaNeural",
        "name": "Neerja",
        "gender": "Female",
        "locale": "en-IN",
        "style": "Indian English conversational",
    },
    {
        "id": "en-AU-NatashaNeural",
        "name": "Natasha",
        "gender": "Female",
        "locale": "en-AU",
        "style": "Australian conversational",
    },
]

# In-memory audio LRU cache for repeated / preview phrases
_AUDIO_CACHE: Dict[str, bytes] = {}
_MAX_CACHE_ITEMS = 64


class TTSRequest(BaseModel):
    text: str
    voice: Optional[str] = "en-US-AriaNeural"
    rate: Optional[str] = "+0%"
    pitch: Optional[str] = "+0Hz"


from backend.core.speech import clean_spoken_text


def normalize_text_for_speech(raw_text: str, max_chars: int = 250) -> str:
    """
    Clean markdown formatting, code blocks, URLs, tables, and syntactic symbols
    so the assistant sounds like a natural person speaking conversationally in small human-like messages.
    """
    if not raw_text:
        return ""

    # Use speech cleaner to strip tables, headers, pipes, and extract concise human sentence
    cleaned = clean_spoken_text(raw_text, max_chars=max_chars)
    if cleaned:
        return cleaned

    # Fallback to basic clean if needed
    text = raw_text.strip()
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    text = re.sub(r'\|.*\|', '', text)
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'[*_`#]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars].strip()



@router.get("/voices")
async def list_voices():
    """Return available high-quality neural conversational voices."""
    return {"voices": CURATED_VOICES}


@router.post("")
async def generate_speech(req: TTSRequest):
    """
    Generate natural streaming MP3 audio from text using Microsoft Cloud Neural TTS.
    """
    clean_text = normalize_text_for_speech(req.text)
    if not clean_text or len(clean_text) < 1:
        raise HTTPException(status_code=400, detail="Text payload is empty after normalization.")

    voice = req.voice or "en-US-AriaNeural"
    rate = req.rate or "+0%"
    pitch = req.pitch or "+0Hz"

    # Cache lookup
    cache_key = hashlib.sha256(f"{voice}:{rate}:{pitch}:{clean_text}".encode("utf-8")).hexdigest()
    if cache_key in _AUDIO_CACHE:
        logger.debug(f"[TTS] Cache hit for key {cache_key[:8]}")
        return Response(content=_AUDIO_CACHE[cache_key], media_type="audio/mpeg")

    try:
        import edge_tts

        communicate = edge_tts.Communicate(
            text=clean_text,
            voice=voice,
            rate=rate,
            pitch=pitch
        )

        audio_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_chunks.append(chunk["data"])

        if not audio_chunks:
            raise HTTPException(status_code=500, detail="TTS service produced no audio frames.")

        audio_bytes = b"".join(audio_chunks)

        # Store in LRU cache
        if len(_AUDIO_CACHE) >= _MAX_CACHE_ITEMS:
            # Drop oldest key
            oldest_key = next(iter(_AUDIO_CACHE))
            _AUDIO_CACHE.pop(oldest_key, None)
        _AUDIO_CACHE[cache_key] = audio_bytes

        logger.info(f"[TTS] Generated {len(audio_bytes)} bytes of MP3 audio using voice '{voice}'")

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Cache-Control": "public, max-age=3600",
                "Content-Disposition": "inline; filename=\"response.mp3\"",
            }
        )
    except Exception as e:
        logger.error(f"[TTS] Failed to generate speech audio: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"TTS generation error: {str(e)}")
