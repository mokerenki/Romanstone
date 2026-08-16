import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core import instances
from app.services.integration_store import (
    delete_connection,
    get_connection,
    list_connections,
    resolve_status,
    save_connection,
)
from app.services.n8n import INTEGRATION_CONFIG, N8nClient, N8nError
from app.services.nango import NANGO_INTEGRATIONS, NangoClient, NangoError
from app.mcp_clients.base_mcp_client import MCPClient
from app.mcp_clients.user_scoped_tool import UserScopedMCPTool
from app.services.plugin_registry import discover_mcp_workflows, list_plugins, workflow_matches

router = APIRouter(prefix="/api/integrations", tags=["integrations"])

DEFAULT_USER_ID = "anonymous"

INTEGRATION_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "slack",
        "name": "Slack",
        "description": "Search company messages, read channels, and post updates to your workspace.",
        "category": "communication",
        "capabilities": ["Search messages", "Read channels", "Post messages", "Thread replies"],
        "auth_type": "oauth",
        "mcp_id": "slack",
        "icon": "slack",
        "oauth_env": {"client_id": "SLACK_CLIENT_ID", "client_secret": "SLACK_CLIENT_SECRET"},
        "scopes": ["channels:history", "groups:history", "search:read", "chat:write"],
    },
    {
        "id": "google_calendar",
        "name": "Google Calendar",
        "description": "View upcoming meetings, check availability, and create calendar events.",
        "category": "productivity",
        "capabilities": ["List events", "Create events", "Check availability"],
        "auth_type": "oauth",
        "mcp_id": "google_workspace",
        "icon": "calendar",
        "oauth_env": {"client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET"},
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    },
    {
        "id": "google_meet",
        "name": "Google Meet",
        "description": "Schedule and join video meetings through Google Workspace.",
        "category": "communication",
        "capabilities": ["Create Meet links", "List meetings", "Join calls"],
        "auth_type": "oauth",
        "mcp_id": "google_workspace",
        "icon": "video",
        "oauth_env": {"client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET"},
        "scopes": ["https://www.googleapis.com/auth/calendar.events"],
    },
    {
        "id": "notion",
        "name": "Notion",
        "description": "Search pages, read databases, and update workspace content.",
        "category": "productivity",
        "capabilities": ["Search pages", "Read databases", "Create pages"],
        "auth_type": "oauth",
        "mcp_id": "notion",
        "icon": "notion",
        "oauth_env": {"client_id": "NOTION_CLIENT_ID", "client_secret": "NOTION_CLIENT_SECRET"},
        "scopes": ["read_content", "update_content"],
    },
    {
        "id": "salesforce",
        "name": "Salesforce",
        "description": "Query leads, opportunities, accounts, and pipeline data.",
        "category": "crm",
        "capabilities": ["Query records", "Update opportunities", "Account lookup"],
        "auth_type": "oauth",
        "mcp_id": "salesforce",
        "icon": "salesforce",
        "oauth_env": {"client_id": "SALESFORCE_CLIENT_ID", "client_secret": "SALESFORCE_CLIENT_SECRET"},
        "scopes": ["api", "refresh_token"],
    },
    {
        "id": "sage",
        "name": "Sage",
        "description": "Access invoices, customers, and accounting data from Sage.",
        "category": "finance",
        "capabilities": ["Invoice lookup", "Customer records", "Financial reports"],
        "auth_type": "api_key",
        "mcp_id": "sage",
        "icon": "sage",
        "api_key_env": "SAGE_API_KEY",
    },
    {
        "id": "whatsapp",
        "name": "WhatsApp",
        "description": "Send and receive WhatsApp messages for customer communication.",
        "category": "communication",
        "capabilities": ["Send messages", "Receive messages"],
        "auth_type": "api_key",
        "mcp_id": "whatsapp",
        "icon": "whatsapp",
        "api_key_env": "WHATSAPP_API_KEY",
    },
]

CATALOG_BY_ID = {item["id"]: item for item in INTEGRATION_CATALOG}

OAUTH_URLS = {
    "slack": "https://slack.com/oauth/v2/authorize",
    "google_calendar": "https://accounts.google.com/o/oauth2/v2/auth",
    "google_meet": "https://accounts.google.com/o/oauth2/v2/auth",
    "notion": "https://api.notion.com/v1/oauth/authorize",
    "salesforce": "https://login.salesforce.com/services/oauth2/authorize",
}


class ConnectRequest(BaseModel):
    api_key: Optional[str] = Field(default=None, description="API key or bot token")
    token: Optional[str] = Field(default=None, description="OAuth access token")
    connection_id: Optional[str] = Field(default=None, description="Nango connection ID")
    provider_config_key: Optional[str] = Field(default=None, description="Nango provider configuration key")


def _mcp_status() -> Dict[str, bool]:
    registry = instances.mcp_registry
    if not registry:
        return {}
    return {name: bool(client._session) for name, client in registry.clients.items()}


def _catalog_entry_status(
    entry: Dict[str, Any],
    stored: Optional[Dict[str, Any]],
    mcp_status: Dict[str, bool],
) -> str:
    mcp_id = entry.get("mcp_id") or entry["id"]
    mcp_connected = mcp_status.get(mcp_id, False)
    return resolve_status(entry["id"], stored, mcp_connected)


async def _build_catalog(user_id: str) -> List[Dict[str, Any]]:
    stored_connections = await list_connections(user_id)
    mcp_status = _mcp_status()
    catalog: List[Dict[str, Any]] = []
    for entry in INTEGRATION_CATALOG:
        stored = stored_connections.get(entry["id"])
        status = _catalog_entry_status(entry, stored, mcp_status)
        catalog.append(
            {
                **entry,
                "status": status,
                "connected_at": stored.get("connected_at") if stored else None,
            }
        )
    return catalog


async def _build_plugin_registry(user_id: str) -> List[Dict[str, Any]]:
    """Merge durable registry rows, n8n capability, and user connection state."""
    plugins, workflows, connections = await asyncio.gather(
        list_plugins(), discover_mcp_workflows(), list_connections(user_id)
    )
    merged: List[Dict[str, Any]] = []
    for plugin in plugins:
        connection = connections.get(plugin["id"])
        has_workflow = any(workflow_matches(plugin, workflow) for workflow in workflows)
        supported = plugin["auth_status_source"] == "nango" and has_workflow
        merged.append({
            **plugin,
            # Client-facing aliases retained for existing visual components.
            "name": plugin["display_name"],
            "capabilities": plugin["feature_bullets"],
            "has_n8n_mcp_workflow": has_workflow,
            "can_connect": supported,
            "status": "connected" if connection else "disconnected",
            "connected_at": connection.get("connected_at") if connection else None,
        })
    return merged


def _oauth_redirect_uri() -> str:
    base = os.getenv("FRONTEND_URL", "http://localhost:3000").rstrip("/")
    return f"{base}/integrations/oauth/callback"


def _build_oauth_url(entry: Dict[str, Any]) -> Optional[str]:
    integration_id = entry["id"]
    oauth_env = entry.get("oauth_env") or {}
    client_id = os.getenv(oauth_env.get("client_id", ""), "").strip()
    if not client_id:
        return None

    redirect_uri = _oauth_redirect_uri()
    state = integration_id

    if integration_id == "slack":
        params = {
            "client_id": client_id,
            "scope": ",".join(entry.get("scopes", [])),
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{OAUTH_URLS['slack']}?{urlencode(params)}"

    if integration_id in ("google_calendar", "google_meet"):
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(entry.get("scopes", [])),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{OAUTH_URLS['google_calendar']}?{urlencode(params)}"

    if integration_id == "notion":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "owner": "user",
            "state": state,
        }
        return f"{OAUTH_URLS['notion']}?{urlencode(params)}"

    if integration_id == "salesforce":
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        return f"{OAUTH_URLS['salesforce']}?{urlencode(params)}"

    return None


@router.get("/catalog")
async def get_catalog(user_id: str = Query(default=DEFAULT_USER_ID)) -> Dict[str, Any]:
    """Backward-compatible catalog endpoint backed by plugin_registry."""
    catalog = await _build_plugin_registry(user_id)
    connected = [c for c in catalog if c["status"] == "connected"]
    return {"catalog": catalog, "connected_count": len(connected)}


@router.get("/")
async def list_integrations(user_id: str = Query(default=DEFAULT_USER_ID)) -> Dict[str, Any]:
    """Dynamic plugin registry, including live capability and connection state."""
    integrations = await _build_plugin_registry(user_id)
    return {"integrations": integrations}


@router.get("/status")
async def integration_status(user_id: str = Query(default=DEFAULT_USER_ID)) -> Dict[str, Any]:
    """Return the current user's connection state for every registry provider."""
    plugins = await _build_plugin_registry(user_id)
    return {"statuses": [{"provider_key": p["provider_key"], "id": p["id"], "status": p["status"]} for p in plugins]}


@router.get("/{integration_id}")
async def get_integration(integration_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> Dict[str, Any]:
    entry = CATALOG_BY_ID.get(integration_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Integration not found")

    stored = await get_connection(user_id, integration_id)
    mcp_status = _mcp_status()
    mcp_id = entry.get("mcp_id") or integration_id
    tools_count = 0
    registry = instances.mcp_registry
    if registry and mcp_id in registry.clients:
        client = registry.clients[mcp_id]
        if client._tools:
            tools_count = len(client._tools)

    return {
        **entry,
        "status": _catalog_entry_status(entry, stored, mcp_status),
        "connected_at": stored.get("connected_at") if stored else None,
        "tools_count": tools_count,
    }


@router.get("/{integration_id}/connect")
async def get_connect_info(
    integration_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
    tenant_id: str = Query(default="default"),
) -> Dict[str, Any]:
    """Create a short-lived Nango Connect session for OAuth providers."""
    entry = CATALOG_BY_ID.get(integration_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Integration not found")

    if integration_id in NANGO_INTEGRATIONS:
        try:
            return {"auth_type": "nango", **(await NangoClient().create_connect_session(user_id, tenant_id, integration_id))}
        except NangoError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    if entry.get("auth_type") == "api_key":
        return {
            "auth_type": "api_key",
            "message": f"Enter your {entry['name']} API key to connect.",
            "env_var": entry.get("api_key_env"),
        }

    return {
        "auth_type": "manual",
        "message": (
            f"Configure OAuth credentials for {entry['name']} "
            f"({', '.join(entry.get('oauth_env', {}).values())}) or connect with an API token."
        ),
    }


@router.post("/{integration_id}/connect")
async def connect_integration(
    integration_id: str,
    body: ConnectRequest,
    user_id: str = Query(default=DEFAULT_USER_ID),
) -> Dict[str, Any]:
    """Provision the user's encrypted n8n credential and MCP workflow."""
    entry = CATALOG_BY_ID.get(integration_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Integration not found")

    now = datetime.now(timezone.utc).isoformat()
    if integration_id in NANGO_INTEGRATIONS:
        connection_id = (body.connection_id or "").strip()
        provider_config_key = (body.provider_config_key or "").strip()
        if not connection_id or not provider_config_key:
            raise HTTPException(status_code=400, detail="Nango connection ID and provider configuration key are required")
        if provider_config_key != NANGO_INTEGRATIONS[integration_id]:
            raise HTTPException(status_code=400, detail="Unexpected Nango provider configuration")
        try:
            provisioned = await N8nClient().provision(integration_id, user_id, connection_id, provider_config_key)
        except N8nError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        await save_connection(
            user_id,
            integration_id,
            auth_type="n8n",
            connected_at=now,
            metadata={**provisioned, "nango_connection_id": connection_id, "nango_provider_config_key": provider_config_key},
        )
        await _register_n8n_tools(integration_id, provisioned)
        return {
            "status": "connected",
            "integration_id": integration_id,
            "connected_at": now,
            "workflow_id": provisioned["workflow_id"],
        }

    credential = (body.api_key or body.token or "").strip()
    if not credential:
        raise HTTPException(status_code=400, detail="API key or token is required")
    await save_connection(
        user_id,
        integration_id,
        auth_type=entry.get("auth_type", "api_key"),
        connected_at=now,
        metadata={"has_credential": True},
    )
    return {"status": "connected", "integration_id": integration_id, "connected_at": now}


@router.post("/{integration_id}/disconnect")
async def disconnect_integration(
    integration_id: str,
    user_id: str = Query(default=DEFAULT_USER_ID),
) -> Dict[str, Any]:
    entry = CATALOG_BY_ID.get(integration_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Integration not found")

    connection = await get_connection(user_id, integration_id)
    if connection and connection.get("auth_type") == "n8n":
        await N8nClient().delete(connection.get("metadata", {}))
    await delete_connection(user_id, integration_id)
    return {"status": "disconnected", "integration_id": integration_id}


async def _register_n8n_tools(integration_id: str, metadata: Dict[str, Any]) -> int:
    """Discover n8n tools once, then register secure current-user wrappers."""
    registry = instances.mcp_registry
    tool_registry = instances.tool_registry
    if not registry or not tool_registry:
        return 0
    client = MCPClient(
        name=f"n8n:{integration_id}",
        url=metadata["mcp_url"],
        headers={"Authorization": f"Bearer {metadata['mcp_token']}"},
    )
    try:
        tools = await client.list_tools()
        for tool in tools:
            tool_registry.register(UserScopedMCPTool(integration_id, tool.name, tool.description or tool.name, tool.inputSchema or {}))
        return len(tools)
    finally:
        await client.close()


@router.post("/{integration_id}/sync")
async def sync_integration(integration_id: str, user_id: str = Query(default=DEFAULT_USER_ID)) -> Dict[str, Any]:
    """Force sync tools from an MCP server."""
    entry = CATALOG_BY_ID.get(integration_id)
    if integration_id in INTEGRATION_CONFIG:
        connection = await get_connection(user_id, integration_id)
        if not connection:
            raise HTTPException(status_code=409, detail="Connect this integration first")
        try:
            tools_count = await _register_n8n_tools(integration_id, connection.get("metadata", {}))
            return {"status": "success", "tools_count": tools_count, "integration_id": integration_id}
        except Exception as exc:
            return {"error": str(exc), "integration_id": integration_id}

    mcp_id = (entry or {}).get("mcp_id") or integration_id

    mcp_registry = instances.mcp_registry
    if not mcp_registry:
        return {"error": "MCP registry not initialized"}

    client = mcp_registry.clients.get(mcp_id)
    if not client:
        return {"error": "Integration not configured on MCP gateway", "integration_id": integration_id}

    try:
        await client.connect()
        tools = await client.list_tools()
        return {"status": "success", "tools_count": len(tools), "integration_id": integration_id}
    except Exception as e:
        return {"error": str(e), "integration_id": integration_id}
