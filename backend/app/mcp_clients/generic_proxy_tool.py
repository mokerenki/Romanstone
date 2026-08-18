"""User-scoped catalog action wrapper for the shared generic-proxy workflow."""

import os
from typing import Any, Dict

from app.core.integration_context import current_integration_user
from app.mcp_clients.base_mcp_client import MCPClient
from app.services.integration_store import get_connection
from app.tools.registry import BaseTool, ToolSchema


class GenericProxyTool(BaseTool):
    def __init__(self, action: Dict[str, Any]):
        self.action = action
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        body = self.action.get("body_template")
        properties = {"query": {"type": "string", "description": "Action-specific query or input."}}
        if body:
            properties["body"] = {"type": "object", "description": "Optional values merged into the action body template."}
        return ToolSchema(name=self.action["tool_name"], description=self.action["description"], parameters=properties)

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        user_id = current_integration_user.get()
        connection = await get_connection(user_id, self.action["plugin_id"])
        metadata = (connection or {}).get("metadata", {})
        connection_id = metadata.get("nango_connection_id")
        if not connection_id:
            raise RuntimeError(f"Connect {self.action['plugin_id']} before using this tool")
        body = self.action.get("body_template") or kwargs.get("body")
        if isinstance(body, dict) and "{{query}}" in body.values():
            body = {key: (kwargs.get("query", "") if value == "{{query}}" else value) for key, value in body.items()}
        client = MCPClient(
            name="generic-proxy",
            url=os.getenv("N8N_GENERIC_MCP_URL", "http://n8n:5678/mcp/generic-proxy/sse"),
            headers={"Authorization": f"Bearer {os.getenv('N8N_GENERIC_MCP_TOKEN', '')}"},
        )
        try:
            result = await client.call_tool("generic_proxy", {
                "tool_name": self.action["tool_name"], "provider": self.action["provider_key"],
                "api_path": self.action["api_path"], "method": self.action["method"],
                "connection_id": connection_id, "body": body,
                "query": kwargs.get("query", ""),
            })
            content = getattr(result, "content", [])
            return {"output": "\n".join(item.text for item in content if hasattr(item, "text")) or str(content)}
        finally:
            await client.close()
