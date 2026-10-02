"""Tool base class and risk levels."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from backend.core.policies import RiskLevel


from typing import Any

@dataclass
class ToolResult:
    success: bool
    output: str = ""
    error: str = ""
    metadata: dict = field(default_factory=dict)
    data: Any = None

    def __post_init__(self):
        if self.data is not None and not self.metadata:
            if isinstance(self.data, dict):
                self.metadata = self.data
        elif self.metadata and self.data is None:
            self.data = self.metadata
        if not self.output and self.data:
            self.output = str(self.data)


class NexusTool(ABC):
    name: str = ""
    description: str = ""
    risk_level: RiskLevel = RiskLevel.SAFE

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        ...

    def run(self, **kwargs) -> ToolResult:
        """Synchronously execute tool, running the async execute coroutine if needed."""
        import asyncio
        import inspect
        coro = self.execute(**kwargs)
        if inspect.iscoroutine(coro):
            try:
                asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, self.execute(**kwargs)).result()
            except RuntimeError:
                return asyncio.run(coro)
        return coro

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "risk_level": self.risk_level.value,
        }
