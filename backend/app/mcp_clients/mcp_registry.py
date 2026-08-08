import os
import json
import yaml
from typing import Dict, Optional, List, Any
from app.mcp_clients.base_mcp_client import MCPClient
from app.mcp_clients.mcp_tool_wrapper import MCPToolWrapper
from app.tools.registry import ToolRegistry
import structlog

logger = structlog.get_logger("aether.mcp.registry")

class MCPRegistry:
    def __init__(self, config_path: Optional[str] = None, cognee_memory: Any = None):
        self.clients: Dict[str, MCPClient] = {}
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config.yaml"
        )
        self._load_config()

    def _load_config(self):
        """Load MCP server definitions from YAML or environment."""
        # Try environment first (MCP_SERVERS can be a JSON dict)
        env_servers = os.getenv("MCP_SERVERS")
        if env_servers:
            servers = json.loads(env_servers)
        elif os.path.exists(self.config_path):
            with open(self.config_path) as f:
                servers = yaml.safe_load(f) or {}
        else:
            servers = {}

        # Expand environment variables in headers
        for name, cfg in servers.items():
            headers = cfg.get("headers", {})
            expanded_headers = {}
            for k, v in headers.items():
                if isinstance(v, str) and v.startswith("${") and v.endswith("}"):
                    env_var = v[2:-1]
                    expanded_headers[k] = os.getenv(env_var, "")
                else:
                    expanded_headers[k] = v

            # For Google services with OAuth, we can provide a headers_provider
            # that refreshes tokens. We'll handle that later.
            self.clients[name] = MCPClient(
                name=name,
                url=cfg["url"],
                headers=expanded_headers,
                timeout=cfg.get("timeout", 30.0),
                sse_read_timeout=cfg.get("sse_read_timeout", 300.0),
            )

    DOMAIN_PROMPTS: Dict[str, str] = {
        "sales": "You are a sales assistant.",
        "marketing": "You are a marketing assistant.",
        "finance": "You are a finance assistant.",
        "executive": "You are an executive assistant.",
        "healthcare": "You are a healthcare admin assistant.",
        "product": "You are a product assistant.",
        "general": "You are a helpful assistant.",
    }

    def get_domain_prompt(self, domain: str) -> str:
        return self.DOMAIN_PROMPTS.get(domain, self.DOMAIN_PROMPTS["general"])

    async def get_domain_context(self, domain: str, user_id: str, thread_id: str) -> Dict[str, Any]:
        return {}

    async def register_all_tools(self, tool_registry: ToolRegistry):
        """Connect to each MCP client, fetch tools, and register them."""
        for name, client in self.clients.items():
            try:
                await client.connect()
                tools = await client.list_tools()
                for tool in tools:
                    wrapper = MCPToolWrapper(
                        mcp_client=client,
                        mcp_tool_name=tool.name,
                        description=tool.description or f"MCP tool: {tool.name}",
                        input_schema=tool.inputSchema or {},
                    )
                    tool_registry.register(wrapper)
                    logger.info("mcp.tool_registered", server=name, tool=tool.name)
            except Exception as e:
                logger.error("mcp.registration_failed", server=name, error=str(e))

    async def close_all(self):
        for client in self.clients.values():
            await client.close()