"""Per-user integration credentials stored in Redis."""

import json
import os
from typing import Any, Dict, Optional

import redis.asyncio as aioredis

from app.core.context import synthai

INTEGRATION_PREFIX = "synthai:integration:"


def _env_connected(integration_id: str) -> bool:
    """True when required env vars for an integration are set."""
    checks: Dict[str, list[str]] = {
        "slack": ["SLACK_BOT_TOKEN", "SLACK_WEBHOOK_URL"],
        "google_calendar": ["GCP_OAUTH_TOKEN", "GOOGLE_CALENDAR_TOKEN"],
        "google_meet": ["GCP_OAUTH_TOKEN", "GOOGLE_MEET_TOKEN"],
        "google_workspace": ["GCP_OAUTH_TOKEN"],
        "notion": ["NOTION_API_KEY", "NOTION_TOKEN"],
        "salesforce": ["SALESFORCE_ACCESS_TOKEN"],
        "sage": ["SAGE_API_KEY", "SAGE_CLIENT_ID"],
        "whatsapp": ["WHATSAPP_API_KEY"],
    }
    for var in checks.get(integration_id, []):
        if os.getenv(var, "").strip():
            return True
    return False


async def _redis() -> Optional[aioredis.Redis]:
    synthai.ensure_initialized()
    return synthai.redis_client


async def get_connection(user_id: str, integration_id: str) -> Optional[Dict[str, Any]]:
    client = await _redis()
    if not client:
        return None
    raw = await client.get(f"{INTEGRATION_PREFIX}{user_id}:{integration_id}")
    if not raw:
        return None
    return json.loads(raw)


async def list_connections(user_id: str) -> Dict[str, Dict[str, Any]]:
    client = await _redis()
    if not client:
        return {}
    keys = [k async for k in client.scan_iter(f"{INTEGRATION_PREFIX}{user_id}:*")]
    out: Dict[str, Dict[str, Any]] = {}
    for key in keys:
        raw = await client.get(key)
        if not raw:
            continue
        integration_id = key.decode().split(":")[-1] if isinstance(key, bytes) else key.split(":")[-1]
        out[integration_id] = json.loads(raw)
    return out


async def save_connection(
    user_id: str,
    integration_id: str,
    *,
    auth_type: str,
    connected_at: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    client = await _redis()
    if not client:
        return
    payload = {
        "integration_id": integration_id,
        "auth_type": auth_type,
        "connected_at": connected_at,
        "metadata": metadata or {},
    }
    await client.set(f"{INTEGRATION_PREFIX}{user_id}:{integration_id}", json.dumps(payload))


async def delete_connection(user_id: str, integration_id: str) -> None:
    client = await _redis()
    if not client:
        return
    await client.delete(f"{INTEGRATION_PREFIX}{user_id}:{integration_id}")


def resolve_status(integration_id: str, stored: Optional[Dict[str, Any]], mcp_connected: bool) -> str:
    if mcp_connected:
        return "connected"
    if stored:
        return "connected"
    if _env_connected(integration_id):
        return "connected"
    return "disconnected"
