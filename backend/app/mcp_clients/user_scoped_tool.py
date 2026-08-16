"""An MCP tool wrapper that resolves its n8n endpoint for the active user."""

from typing import Any, Dict

from app.core.integration_context import current_integration_user
from app.mcp_clients.base_mcp_client import MCPClient
from app.services.integration_store import get_connection
from app.tools.registry import BaseTool, ToolSchema


class UserScopedMCPTool(BaseTool):
    def __init__(self, integration_id: str, tool_name: str, description: str, input_schema: Dict[str, Any]):
        self.integration_id = integration_id
        self.tool_name = tool_name
        self.description = description
        self.input_schema = input_schema
        super().__init__()

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=f"{self.integration_id}_{self.tool_name}",
            description=f"{self.description} (uses the current user's {self.integration_id} connection)",
            parameters=self.input_schema.get("properties", {}),
            required=self.input_schema.get("required", []),
        )

    async def execute(self, **kwargs: Any) -> Dict[str, Any]:
        user_id = current_integration_user.get()
        connection = await get_connection(user_id, self.integration_id)
        metadata = (connection or {}).get("metadata", {})
        if not metadata.get("mcp_url") or not metadata.get("mcp_token"):
            raise RuntimeError(f"Connect {self.integration_id} before using this tool")
        client = MCPClient(
            name=f"{self.integration_id}:{user_id}",
            url=metadata["mcp_url"],
            headers={"Authorization": f"Bearer {metadata['mcp_token']}"},
        )
        try:
            result = await client.call_tool(self.tool_name, kwargs)
            content = getattr(result, "content", [])
            text = "\n".join(item.text for item in content if hasattr(item, "text"))
            return {"output": text or str(content or result)}
        finally:
            await client.close()
