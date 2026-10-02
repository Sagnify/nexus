"""Current date, time, and timezone tool for NEXUS."""
from __future__ import annotations
import datetime
import time
from backend.agent.tools.base import NexusTool, ToolResult


class CurrentTimeTool(NexusTool):
    name = "get_current_time"
    description = "Get the exact current local and UTC date, time, weekday, and timezone."

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": {},
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        now_local = datetime.datetime.now()
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        tz_name = time.tzname[time.daylight] if time.daylight else time.tzname[0]

        output = (
            f"Current Local Date & Time: {now_local.strftime('%A, %B %d, %Y %I:%M:%S %p')}\n"
            f"Weekday: {now_local.strftime('%A')}\n"
            f"Timezone: {tz_name}\n"
            f"UTC Timestamp: {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}"
        )
        return ToolResult(success=True, output=output)
