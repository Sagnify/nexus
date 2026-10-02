"""Model registry — central store of all available model profiles."""
from __future__ import annotations
from backend.agent.router.capabilities import ModelProfile, GROQ_PROFILES


class ModelRegistry:
    def __init__(self):
        self._profiles: dict[str, ModelProfile] = {}
        for profile in GROQ_PROFILES:
            self.register(profile)

    def register(self, profile: ModelProfile) -> None:
        self._profiles[profile.name] = profile

    def get(self, name: str) -> ModelProfile | None:
        return self._profiles.get(name)

    def find(
        self,
        *,
        vision: bool = False,
        tool_calling: bool = False,
        reasoning: bool = False,
        speed: str | None = None,
        tag: str | None = None,
    ) -> list[ModelProfile]:
        results = list(self._profiles.values())
        if vision:
            results = [m for m in results if m.vision]
        if tool_calling:
            results = [m for m in results if m.tool_calling]
        if reasoning:
            results = [m for m in results if m.reasoning]
        if speed:
            results = [m for m in results if m.speed == speed]
        if tag:
            results = [m for m in results if tag in m.tags]
        return results

    def all(self) -> list[ModelProfile]:
        return list(self._profiles.values())


# Singleton
registry = ModelRegistry()
