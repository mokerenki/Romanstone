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
    },
    "notion": {
        "proxy_path": "search",
    },
    "google_calendar": {"proxy_path": "calendar/v3/users/me/calendarList"},
    "google_meet": {"proxy_path": "calendar/v3/users/me/events"},
    "salesforce": {"proxy_path": "services/data"},
}


class N8nClient:
    def __init__(self) -> None:
        self.base_url = os.getenv("N8N_API_URL", "http://n8n:5678").rstrip("/")
        self.api_key = os.getenv("N8N_API_KEY", "").strip()
        # n8n generates this public URL into the MCP Server Trigger metadata.
        self.public_url = os.getenv("N8N_PUBLIC_URL", "http://localhost:5678").rstrip("/")

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
        action_name = f"{integration_id.title()} action"
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
                    "type": "n8n-nodes-base.httpRequest",
                    "typeVersion": 2,
                    "position": [520, 300],
                    "parameters": {
                        "method": "GET",
                        "url": f"={{ $env.NANGO_PROXY_URL + '/proxy/{cfg['proxy_path']}' }}",
                        "sendHeaders": True,
                        "headerParameters": {"parameters": [
                            {"name": "Authorization", "value": "={{ 'Bearer ' + $env.NANGO_SECRET_KEY }}"},
                            {"name": "Connection-Id", "value": connection_id},
                            {"name": "Provider-Config-Key", "value": provider_config_key},
                        ]},
                    },
                },
            ],
            "connections": {trigger_name: {"main": [[{"node": action_name, "type": "main", "index": 0}]]}},
            "tags": [],
        }

    async def provision(self, integration_id: str, user_id: str, connection_id: str, provider_config_key: str) -> Dict[str, str]:
        if integration_id not in INTEGRATION_CONFIG:
            raise N8nError(f"n8n workflow template is not available for {integration_id}")
        suffix = self._safe_id(user_id)
        # This credential protects the MCP endpoint only; provider OAuth
        # credentials remain exclusively in Nango.
        mcp_token = secrets.token_urlsafe(32)
        trigger_credential = await self._request("POST", "/credentials", {
            "name": f"SynthAI {integration_id} MCP {suffix}",
            "type": "httpBearerAuth",
            "data": {"token": mcp_token},
        })
        workflow = await self._request("POST", "/workflows", self._workflow(integration_id, user_id, connection_id, provider_config_key, trigger_credential["id"]))
        await self._request("POST", f"/workflows/{workflow['id']}/activate")
        endpoint = f"{self.public_url}/mcp/synthai-{integration_id}-{suffix}/sse"
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
