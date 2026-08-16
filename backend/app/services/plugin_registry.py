"""Persistent plugin registry and n8n MCP capability discovery."""

import asyncio
import os
from dataclasses import dataclass
from typing import Any, Dict, List

import psycopg

from app.services.n8n import N8nClient, N8nError


@dataclass(frozen=True)
class PluginRegistry:
    id: str
    provider_key: str
    display_name: str
    description: str
    category: str
    icon: str
    feature_bullets: List[str]
    n8n_workflow_id: str | None
    auth_status_source: str


SEED_PLUGINS = [
    PluginRegistry("slack", "slack", "Slack", "Search company messages, read channels, and post updates.", "Communication", "slack", ["Search messages", "Read channels", "Post messages", "Thread replies"], None, "nango"),
    PluginRegistry("google_calendar", "google", "Google Calendar", "View meetings, check availability, and create events.", "Productivity", "calendar", ["List events", "Create events", "Check availability"], "IfXEH1PKJvVxImTc", "nango"),
    PluginRegistry("google_meet", "google", "Google Meet", "Schedule meetings and generate Meet links through Google Workspace.", "Communication", "video", ["Create Meet links", "List meetings", "Schedule calls"], None, "nango"),
    PluginRegistry("notion", "notion", "Notion", "Search pages, read databases, and update workspace content.", "Productivity", "notion", ["Search pages", "Read databases", "Create pages"], None, "nango"),
    PluginRegistry("salesforce", "salesforce", "Salesforce", "Query leads, opportunities, accounts, and pipeline data.", "CRM", "salesforce", ["Query records", "Update opportunities", "Account lookup"], None, "nango"),
    # TODO: Sage authentication varies by Sage product and needs its own investigation.
    PluginRegistry("sage", "sage", "Sage", "Access invoices, customers, and accounting data from Sage.", "Finance", "sage", ["Invoice lookup", "Customer records", "Financial reports"], None, "unsupported"),
    # TODO: WhatsApp requires Meta Business API and embedded signup research.
    PluginRegistry("whatsapp", "whatsapp", "WhatsApp", "Send and receive WhatsApp messages for customer communication.", "Communication", "whatsapp", ["Send messages", "Receive messages"], None, "unsupported"),
]


def _dsn() -> str:
    return os.getenv("DATABASE_URL", "postgresql://aether:aether@postgres:5432/aether").replace("postgresql+asyncpg://", "postgresql://")


def _initialize_sync() -> None:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS plugin_registry (
                id TEXT PRIMARY KEY, provider_key TEXT NOT NULL, display_name TEXT NOT NULL,
                description TEXT NOT NULL, category TEXT NOT NULL, icon TEXT NOT NULL,
                feature_bullets TEXT[] NOT NULL, n8n_workflow_id TEXT NULL,
                auth_status_source TEXT NOT NULL CHECK (auth_status_source IN ('nango','manual','unsupported'))
            )
        """)
        for plugin in SEED_PLUGINS:
            cur.execute("""
                INSERT INTO plugin_registry (id, provider_key, display_name, description, category, icon, feature_bullets, n8n_workflow_id, auth_status_source)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (id) DO NOTHING
            """, (plugin.id, plugin.provider_key, plugin.display_name, plugin.description, plugin.category, plugin.icon, plugin.feature_bullets, plugin.n8n_workflow_id, plugin.auth_status_source))


def _list_sync() -> List[Dict[str, Any]]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, provider_key, display_name, description, category, icon, feature_bullets, n8n_workflow_id, auth_status_source FROM plugin_registry ORDER BY display_name")
        keys = [column.name for column in cur.description]
        return [dict(zip(keys, row)) for row in cur.fetchall()]


async def ensure_registry() -> None:
    await asyncio.to_thread(_initialize_sync)


async def list_plugins() -> List[Dict[str, Any]]:
    await ensure_registry()
    return await asyncio.to_thread(_list_sync)


async def discover_mcp_workflows() -> List[Dict[str, Any]]:
    """Return n8n workflows that contain an MCP Server Trigger node."""
    try:
        workflows = await N8nClient().list_workflows()
    except N8nError:
        return []
    return [
        workflow for workflow in workflows
        if any(str(node.get("type", "")).endswith("mcpTrigger") for node in workflow.get("nodes", []))
    ]


def workflow_matches(plugin: Dict[str, Any], workflow: Dict[str, Any]) -> bool:
    if plugin.get("n8n_workflow_id") and str(workflow.get("id")) == str(plugin["n8n_workflow_id"]):
        return True
    provider = plugin["provider_key"].lower()
    name = str(workflow.get("name", "")).lower()
    tags = " ".join(str(tag.get("name", tag)) for tag in workflow.get("tags", [])).lower()
    return provider in name or provider in tags
