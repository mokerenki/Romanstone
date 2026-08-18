"""Durable catalog for parameterized actions served by the generic n8n proxy."""

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List

import psycopg

from app.services.plugin_registry import _dsn


@dataclass(frozen=True)
class ActionCatalogEntry:
    tool_name: str
    plugin_id: str
    provider_key: str
    api_path: str
    method: str
    description: str
    body_template: Dict[str, Any] | None = None


SEED_ACTIONS = [
    ActionCatalogEntry("salesforce_query_leads", "salesforce", "salesforce", "services/data/v59.0/query", "GET", "Query Salesforce leads using a SOQL query supplied as the query parameter."),
    ActionCatalogEntry("salesforce_list_accounts", "salesforce", "salesforce", "services/data/v59.0/sobjects/Account", "GET", "List Salesforce accounts available to the connected user."),
    ActionCatalogEntry("notion_search", "notion", "notion", "search", "POST", "Search pages and databases in the connected Notion workspace.", {"query": "{{query}}"}),
    ActionCatalogEntry("slack_list_channels", "slack", "slack", "conversations.list", "GET", "List channels in the connected Slack workspace."),
]


def _initialize_sync() -> None:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS action_catalog (
                tool_name TEXT PRIMARY KEY, plugin_id TEXT NOT NULL REFERENCES plugin_registry(id),
                provider_key TEXT NOT NULL, api_path TEXT NOT NULL, method TEXT NOT NULL,
                description TEXT NOT NULL, body_template JSONB NULL
            )
        """)
        for entry in SEED_ACTIONS:
            cur.execute("""
                INSERT INTO action_catalog (tool_name, plugin_id, provider_key, api_path, method, description, body_template)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tool_name) DO NOTHING
            """, (entry.tool_name, entry.plugin_id, entry.provider_key, entry.api_path, entry.method, entry.description, psycopg.types.json.Jsonb(entry.body_template) if entry.body_template else None))


def _list_sync() -> List[Dict[str, Any]]:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        cur.execute("SELECT tool_name, plugin_id, provider_key, api_path, method, description, body_template FROM action_catalog ORDER BY tool_name")
        keys = [column.name for column in cur.description]
        return [dict(zip(keys, row)) for row in cur.fetchall()]


def _upsert_sync(entries: List[ActionCatalogEntry]) -> None:
    with psycopg.connect(_dsn()) as conn, conn.cursor() as cur:
        for entry in entries:
            cur.execute("""
                INSERT INTO action_catalog (tool_name, plugin_id, provider_key, api_path, method, description, body_template)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (tool_name) DO UPDATE SET plugin_id=EXCLUDED.plugin_id, provider_key=EXCLUDED.provider_key,
                api_path=EXCLUDED.api_path, method=EXCLUDED.method, description=EXCLUDED.description, body_template=EXCLUDED.body_template
            """, (entry.tool_name, entry.plugin_id, entry.provider_key, entry.api_path, entry.method, entry.description, psycopg.types.json.Jsonb(entry.body_template) if entry.body_template else None))


async def ensure_action_catalog() -> None:
    await asyncio.to_thread(_initialize_sync)


async def list_actions() -> List[Dict[str, Any]]:
    await ensure_action_catalog()
    return await asyncio.to_thread(_list_sync)


async def upsert_actions(entries: List[ActionCatalogEntry]) -> None:
    await ensure_action_catalog()
    await asyncio.to_thread(_upsert_sync, entries)
