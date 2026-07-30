import structlog
from typing import List, Dict, Any, Optional, Callable, Awaitable
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.types import Tool as MCPTool
import asyncio

logger = structlog.get_logger("aether.mcp.base")

class MCPClient:
    """Manages a connection to a single MCP server and exposes its tools."""

    def __init__(
        self,
        name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        headers_provider: Optional[Callable[[], Awaitable[Dict[str, str]]]] = None,
        timeout: float = 30.0,
        sse_read_timeout: float = 300.0
    ):
        self.name = name
        self.url = url
        self.headers = headers or {}
        self.headers_provider = headers_provider
        self.timeout = timeout
        self.sse_read_timeout = sse_read_timeout
        self._session: Optional[ClientSession] = None
        self._sse = None
        self._tools: List[MCPTool] = []

    async def _get_headers(self) -> Dict[str, str]:
        """Get headers, optionally via a provider."""
        if self.headers_provider:
            return await self.headers_provider()
        return self.headers

    async def connect(self):
        """Establish SSE connection and initialize session."""
        logger.info("mcp_client.connecting", name=self.name, url=self.url)
        headers = await self._get_headers()
        self._sse = sse_client(self.url, headers=headers, timeout=self.timeout)
        read_stream, write_stream = await self._sse.__aenter__()
        self._session = ClientSession(read_stream, write_stream)
        await self._session.initialize()
        logger.info("mcp_client.connected", name=self.name)

    async def list_tools(self) -> List[MCPTool]:
        """Fetch all tools from the server."""
        if self._session is None:
            await self.connect()
        result = await self._session.list_tools()
        self._tools = result.tools
        logger.info("mcp_client.tools_fetched", name=self.name, count=len(self._tools))
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        """Call a tool on the server."""
        if self._session is None:
            await self.connect()
        result = await self._session.call_tool(tool_name, arguments)
        return result

    async def close(self):
        if self._session:
            await self._session.close()
        if self._sse:
            await self._sse.__aexit__(None, None, None)
        logger.info("mcp_client.closed", name=self.name)