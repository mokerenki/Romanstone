"""
CalendarTool - Create calendar events.
"""

import os
from datetime import datetime, timezone
from typing import Any, Dict

import structlog

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.calendar")


class CalendarTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.provider = os.getenv("CALENDAR_PROVIDER", "local")

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="calendar",
            description="Create a calendar event. Configure CALENDAR_PROVIDER to 'google', 'outlook', or 'local'.",
            parameters={
                "title": {"type": "string", "description": "Event title"},
                "start": {"type": "string", "description": "Start ISO 8601 timestamp"},
                "end": {"type": "string", "description": "End ISO 8601 timestamp"},
                "attendees": {"type": "array", "items": {"type": "string"}, "description": "Attendee emails"},
                "location": {"type": "string", "description": "Event location"},
                "notes": {"type": "string", "description": "Event description/notes"},
            },
            required=["title", "start", "end"],
            irreversible=True,
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        event = {
            "title": kwargs.get("title", "Untitled"),
            "start": kwargs.get("start"),
            "end": kwargs.get("end"),
            "attendees": kwargs.get("attendees", []),
            "location": kwargs.get("location", ""),
            "notes": kwargs.get("notes", ""),
            "provider": self.provider,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if self.provider == "google":
            return await self._google_create(event)
        if self.provider == "outlook":
            return await self._outlook_create(event)
        logger.info("calendar.local_create", event=event)
        return {"output": f"Calendar event created locally: {event['title']} ({event['start']} - {event['end']})", "event": event}

    async def _google_create(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return {"output": "Google Calendar provider not yet wired.", "event": event}

    async def _outlook_create(self, event: Dict[str, Any]) -> Dict[str, Any]:
        return {"output": "Outlook Calendar provider not yet wired.", "event": event}
