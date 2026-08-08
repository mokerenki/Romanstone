"""
SlackTool - Post messages to Slack via incoming webhook or bot token.
"""

import os
from typing import Any, Dict, Optional

import httpx
import structlog

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.slack")


class SlackTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.webhook_url = os.getenv("SLACK_WEBHOOK_URL", "")
        self.bot_token = os.getenv("SLACK_BOT_TOKEN", "")
        self.channel = os.getenv("SLACK_CHANNEL", "#general")

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="slack",
            description="Post a message to Slack via webhook or bot token.",
            parameters={
                "message": {"type": "string", "description": "Message text to post"},
                "channel": {"type": "string", "description": "Override destination channel"},
                "blocks": {"type": "array", "description": "Optional Slack Block Kit JSON array"},
            },
            required=["message"],
            irreversible=True,
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        message = kwargs.get("message", "")
        channel = kwargs.get("channel") or self.channel
        blocks = kwargs.get("blocks")
        if not message and not blocks:
            return {"output": "Error: message or blocks are required."}
        if self.webhook_url:
            return await self._post_webhook(message, blocks)
        if self.bot_token:
            return await self._post_bot(channel, message, blocks)
        return {"output": "Error: Slack not configured (SLACK_WEBHOOK_URL or SLACK_BOT_TOKEN)."}

    async def _post_webhook(self, message: str, blocks: Optional[list]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"text": message}
        if blocks:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.webhook_url, json=payload)
                resp.raise_for_status()
            return {"output": "Message posted to Slack webhook."}
        except Exception as exc:
            logger.error("slack.webhook_failed", error=str(exc))
            return {"output": f"Error posting to Slack: {exc}"}

    async def _post_bot(self, channel: str, message: str, blocks: Optional[list]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"channel": channel, "text": message}
        if blocks:
            payload["blocks"] = blocks
        try:
            async with httpx.AsyncClient(timeout=10.0, headers={"Authorization": f"Bearer {self.bot_token}", "Content-Type": "application/json"}) as client:
                resp = await client.post("https://slack.com/api/chat.postMessage", json=payload)
                resp.raise_for_status()
                data = resp.json()
                if not data.get("ok"):
                    return {"output": f"Slack API error: {data.get('error')}"}
            return {"output": f"Message posted to Slack channel {channel}."}
        except Exception as exc:
            logger.error("slack.bot_failed", error=str(exc))
            return {"output": f"Error posting to Slack: {exc}"}
