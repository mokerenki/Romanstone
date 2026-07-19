from app.tools.registry import BaseTool, ToolSchema
from app.mcp_clients.base_mcp_client import MCPClient
from typing import Dict, Any

class MCPToolWrapper(BaseTool):
    """Wrapper that makes any MCP tool callable via our ToolRegistry."""

    def __init__(self, mcp_client: MCPClient, mcp_tool_name: str, description: str, input_schema: Dict[str, Any]):
        super().__init__()
        self._client = mcp_client
        self._mcp_tool_name = mcp_tool_name
        self._description = description
        self._input_schema = input_schema

    def _build_schema(self) -> ToolSchema:
        parameters = self._input_schema.get("properties", {})
        required = self._input_schema.get("required", [])
        return ToolSchema(
            name=self._mcp_tool_name,
            description=self._description,
            parameters=parameters,
            required=required,
        )

    async def execute(self, **kwargs) -> Any:
        """Call the remote MCP tool with the given arguments."""
        result = await self._client.call_tool(self._mcp_tool_name, kwargs)
        # Extract textual content from result
        if hasattr(result, 'content') and result.content:
            texts = [item.text for item in result.content if hasattr(item, 'text')]
            if texts:
                return {"output": "\n".join(texts)}
            return {"output": result.content}
        return {"output": str(result)}