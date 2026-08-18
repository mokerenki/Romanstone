"""n8n MCP workflow provisioning backed by Nango's authenticated proxy."""

import hashlib
import os
import secrets
from typing import Any, Dict, List

import httpx


class N8nError(RuntimeError):
    pass


INTEGRATION_CONFIG: Dict[str, Dict[str, str]] = {
    "slack": {
        "proxy_path": "conversations.list",
        "tool_name": "List Slack Channels",
    },
    "notion": {
        "proxy_path": "search",
        "tool_name": "Search Notion",
    },
    "google_calendar": {
        "proxy_path": "calendar/v3/calendars/primary/events",
        "tool_name": "List Calendar Events",
    },
    "google_meet": {
        "proxy_path": "calendar/v3/users/me/events",
        "tool_name": "List Google Meet Events",
    },
    "salesforce": {"proxy_path": "services/data", "tool_name": "Query Salesforce"},
}


class N8nClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("N8N_API_URL", "http://n8n:5678").rstrip("/")
        self.api_key = os.getenv("N8N_API_KEY", "").strip()
        # Browser-facing n8n URLs use localhost, but requests made by this
        # backend must use Docker's service hostname instead of localhost.
        self.public_url = os.getenv("N8N_PUBLIC_URL", "http://localhost:5678").rstrip("/")
        self.internal_mcp_url = os.getenv("N8N_INTERNAL_MCP_URL", self.base_url).rstrip("/")

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise N8nError("N8N_API_KEY is not configured")
        return {"X-N8N-API-KEY": self.api_key, "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.request(method, f"{self.base_url}/api/v1{path}", headers=self._headers(), json=payload)
        except httpx.HTTPError as exc:
            raise N8nError(f"n8n is unavailable: {exc}") from exc
        if response.is_error:
            raise N8nError(f"n8n API {response.status_code}: {response.text[:500]}")
        return response.json()

    async def list_workflows(self) -> List[Dict[str, Any]]:
        response = await self._request("GET", "/workflows")
        return response.get("data", response if isinstance(response, list) else [])

    async def ensure_generic_proxy(self) -> Dict[str, str]:
        """Create the shared long-tail MCP proxy without touching dedicated workflows."""
        existing = next((w for w in await self.list_workflows() if w.get("name") == "SynthAI · generic-proxy"), None)
        token = os.getenv("N8N_GENERIC_MCP_TOKEN", "").strip()
        if not token:
            raise N8nError("N8N_GENERIC_MCP_TOKEN is not configured")
        if existing:
            return {"workflow_id": str(existing["id"]), "mcp_url": f"{self.public_url}/mcp/generic-proxy/sse"}
        credential = await self._request("POST", "/credentials", {"name": "SynthAI generic-proxy MCP", "type": "httpBearerAuth", "data": {"token": token}})
        trigger = "MCP Server Trigger"
        workflow = await self._request("POST", "/workflows", {
            # n8n's public workflow-create API rejects `tags` as read-only.
            # The deterministic workflow name is the discovery convention.
            "name": "SynthAI · generic-proxy", "settings": {"executionOrder": "v1"},
            "nodes": [
                {"id": "generic-mcp", "name": trigger, "type": "@n8n/n8n-nodes-langchain.mcpTrigger", "typeVersion": 1.1,
                 "position": [260, 300], "parameters": {"path": "generic-proxy", "authentication": "bearerAuth"},
                 "credentials": {"httpBearerAuth": {"id": credential["id"], "name": "SynthAI generic-proxy MCP"}}},
                {"id": "nango-proxy", "name": "Nango Proxy", "type": "n8n-nodes-base.httpRequest", "typeVersion": 2,
                 "position": [540, 300], "parameters": {"method": "={{ $json.method }}", "url": "={{ $vars.NANGO_PROXY_URL + '/proxy/' + $json.api_path }}",
                 "sendHeaders": True, "headerParameters": {"parameters": [
                    {"name": "Authorization", "value": "={{ 'Bearer ' + $vars.NANGO_SECRET_KEY }}"},
                    {"name": "Connection-Id", "value": "={{ $json.connection_id }}"},
                    {"name": "Provider-Config-Key", "value": "={{ $json.provider }}"}]},
                 "sendBody": True, "specifyBody": "json", "jsonBody": "={{ $json.body }}"}},
            ], "connections": {trigger: {"main": [[{"node": "Nango Proxy", "type": "main", "index": 0}]]}},
        })
        await self._request("POST", f"/workflows/{workflow['id']}/activate")
        return {"workflow_id": str(workflow["id"]), "mcp_url": f"{self.public_url}/mcp/generic-proxy/sse"}

    @staticmethod
    def _safe_id(user_id: str) -> str:
        return hashlib.sha256(user_id.encode()).hexdigest()[:12]

    def _workflow(self, integration_id: str, user_id: str, connection_id: str, provider_config_key: str, credential_id: str) -> Dict[str, Any]:
        """Create one isolated workflow per user/integration.

        MCP Server Trigger is deliberately the entry node: n8n trigger nodes
        start workflows. The attached app node is where the action executes.
        """
        cfg = INTEGRATION_CONFIG[integration_id]
        suffix = self._safe_id(user_id)
        trigger_name = "MCP Server Trigger"
        action_name = cfg.get("tool_name", f"{integration_id.title()} action")
        return {
            "name": f"SynthAI · {integration_id} · {suffix}",
            "settings": {"executionOrder": "v1"},
            "nodes": [
                {
                    "id": f"mcp-{suffix}",
                    "name": trigger_name,
                    "type": "@n8n/n8n-nodes-langchain.mcpTrigger",
                    "typeVersion": 1.1,
                    "position": [260, 300],
                    "parameters": {"path": f"synthai-{integration_id}-{suffix}", "authentication": "bearerAuth"},
                    "credentials": {"httpBearerAuth": {"id": credential_id, "name": f"SynthAI {integration_id} MCP {suffix}"}},
                },
                {
                    "id": f"action-{suffix}",
                    "name": action_name,
                    # MCP Server Trigger only exposes AI tool nodes. A normal
                    # HTTP Request node on the main branch cannot be invoked
                    # by an MCP client.
                    "type": "n8n-nodes-base.httpRequestTool",
                    "typeVersion": 4.5,
                    "position": [520, 300],
                    "parameters": {
                        "method": "GET",
                        # This is an f-string, so each n8n expression brace
                        # must be doubled twice to retain `={{ ... }}` in the
                        # workflow JSON rather than becoming `={ ... }`.
                        "url": f"={{{{ $env.NANGO_PROXY_URL + '/proxy/{cfg['proxy_path']}' }}}}",
                        "sendHeaders": True,
                        "headerParameters": {"parameters": [
                            {"name": "Authorization", "value": "={{ 'Bearer ' + $env.NANGO_SECRET_KEY }}"},
                            {"name": "Connection-Id", "value": connection_id},
                            {"name": "Provider-Config-Key", "value": provider_config_key},
                        ]},
                        "options": {},
                    },
                },
            ],
            # Tags are read-only in n8n's public workflow-create API. The
            # provider-specific workflow name remains the discovery key.
            "connections": {action_name: {"ai_tool": [[{"node": trigger_name, "type": "ai_tool", "index": 0}]]}},
        }

    async def provision(self, integration_id: str, user_id: str, connection_id: str, provider_config_key: str) -> Dict[str, str]:
        if integration_id not in INTEGRATION_CONFIG:
            raise N8nError(f"n8n workflow template is not available for {integration_id}")
        suffix = self._safe_id(user_id)
        # This credential protects the MCP endpoint only; provider OAuth
        # credentials remain exclusively in Nango.
        workflow_name = f"SynthAI · {integration_id} · {suffix}"
        # Remove a partially provisioned workflow from a previous failed
        # attempt so its webhook path cannot block this retry with HTTP 409.
        for existing in await self.list_workflows():
            if existing.get("name") == workflow_name:
                await self._request("DELETE", f"/workflows/{existing['id']}")
        mcp_token = secrets.token_urlsafe(32)
        trigger_credential = await self._request("POST", "/credentials", {
            "name": f"SynthAI {integration_id} MCP {suffix}",
            "type": "httpBearerAuth",
            "data": {"token": mcp_token},
        })
        workflow = await self._request("POST", "/workflows", self._workflow(integration_id, user_id, connection_id, provider_config_key, trigger_credential["id"]))
        await self._request("POST", f"/workflows/{workflow['id']}/activate")
        endpoint = f"{self.internal_mcp_url}/mcp/synthai-{integration_id}-{suffix}/sse"
        return {
            "trigger_credential_id": trigger_credential["id"],
            "workflow_id": workflow["id"],
            "mcp_url": endpoint,
            "mcp_token": mcp_token,
        }

    async def delete(self, metadata: Dict[str, Any]) -> None:
        # Best-effort cleanup. A missing n8n record is already disconnected.
        for key in ("workflow_id", "trigger_credential_id"):
            record_id = metadata.get(key)
            if not record_id:
                continue
            path = f"/workflows/{record_id}" if key == "workflow_id" else f"/credentials/{record_id}"
            try:
                await self._request("DELETE", path)
            except N8nError:
                pass
