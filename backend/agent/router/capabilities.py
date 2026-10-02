"""Model capability profiles for routing — verified against actual live Groq models."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class ModelProfile:
    name: str
    provider: str              # "groq"
    model_id: str              # Actual API model ID

    # Capabilities
    text: bool = True
    vision: bool = False
    tool_calling: bool = False
    structured_output: bool = True
    reasoning: bool = False

    # Performance
    speed: str = "medium"      # "fast" | "medium" | "slow"
    context_window: int = 131072

    # Use-case tags
    tags: list[str] = field(default_factory=list)


# Actual live models returned from client.models.list() on Groq and Google AI Studio
GROQ_PROFILES: list[ModelProfile] = [
    ModelProfile(
        name="Qwen 3.8 27B",
        provider="groq",
        model_id="qwen/qwen3.8-27b",
        vision=True,
        tool_calling=True,
        structured_output=True,
        reasoning=True,
        speed="fast",
        context_window=131072,
        tags=["primary", "reasoning", "fast", "vision", "tool", "intent"],
    ),
    ModelProfile(
        name="OpenAI GPT OSS 120B",
        provider="groq",
        model_id="openai/gpt-oss-120b",
        vision=False,
        tool_calling=False,
        structured_output=False,
        reasoning=True,
        speed="medium",
        context_window=131072,
        tags=["reasoning", "planning"],
    ),
    ModelProfile(
        name="OpenAI GPT OSS 20B",
        provider="groq",
        model_id="openai/gpt-oss-20b",
        vision=False,
        tool_calling=False,
        structured_output=False,
        reasoning=False,
        speed="fast",
        context_window=131072,
        tags=["fast", "general"],
    ),
    ModelProfile(
        name="Allam 2 7B",
        provider="groq",
        model_id="allam-2-7b",
        vision=False,
        tool_calling=False,
        structured_output=True,
        reasoning=False,
        speed="fast",
        context_window=131072,
        tags=["fast", "multilingual"],
    ),
    ModelProfile(
        name="Google Gemma 4 (26B)",
        provider="google",
        model_id="google/gemma-4-26b-a4b-it",
        vision=False,
        tool_calling=False,
        structured_output=True,
        reasoning=True,
        speed="fast",
        context_window=131072,
        tags=["reasoning", "planning", "heavy_lifting", "gemma"],
    ),
]
