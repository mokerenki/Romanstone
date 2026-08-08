"""
CurrentTimeTool - Returns the current date and time.
"""

from datetime import datetime, timezone

import structlog

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.current_time")


class CurrentTimeTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="current_time",
            description=(
                "Get the current date and time. Optionally specify a timezone "
                "or output format. Use this when the user asks 'what time is it', "
                "'what's the date', or needs the current timestamp."
            ),
            parameters={
                "timezone": {
                    "type": "string",
                    "description": (
                        "Optional IANA timezone name (e.g. 'America/New_York', "
                        "'Europe/Berlin'). Defaults to UTC if omitted."
                    ),
                },
                "format": {
                    "type": "string",
                    "description": (
                        "Optional output format string (Python strftime format). "
                        "Defaults to ISO 8601 if omitted."
                    ),
                },
            },
            required=[],
        )

    async def execute(self, **kwargs) -> dict:
        tz_name = kwargs.get("timezone")
        fmt = kwargs.get("format")

        try:
            if tz_name:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(tz_name))
            else:
                now = datetime.now(timezone.utc)

            if fmt:
                output = now.strftime(fmt)
            else:
                output = now.isoformat()

            return {"output": output}
        except Exception as e:
            logger.error("current_time.failed", error=str(e))
            return {"output": f"Error getting current time: {e}"}
