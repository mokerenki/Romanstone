# backend/app/mcp_clients/mcp_registry.py

import os
import json
import yaml
import socket
import structlog
from typing import Dict, Optional, List, Any, Tuple

from app.mcp_clients.base_mcp_client import MCPClient
from app.mcp_clients.mcp_tool_wrapper import MCPToolWrapper
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("aether.mcp.registry")


class MCPRegistry:
    """Registry for all MCP clients and their tools."""
    
    def __init__(self, config_path: Optional[str] = None):
        self.clients: Dict[str, MCPClient] = {}
        self._tools_registered = False
        self._initialized = False
        self.config_path = config_path or os.path.join(
            os.path.dirname(__file__), "config.yaml"
        )
        self._mcp_profile_url = os.getenv("MCP_PROFILE_URL", "http://mcp-profile:3000")
        
    async def initialize(self) -> None:
        """Initialize the registry and discover all MCP servers."""
        if self._initialized:
            return
        
        logger.info("mcp_registry.initializing")
        
        # 1. Discover servers from config
        self._discover_from_config()
        
        # 2. Auto-discover Docker MCP services
        self._discover_docker_services()
        
        # 3. Discover from MCP profile
        self._discover_from_mcp_profile()
        
        self._initialized = True
        logger.info("mcp_registry.initialized", 
                    client_count=len(self.clients),
                    clients=list(self.clients.keys()))

    def _discover_from_config(self):
        """Discover MCP servers from config.yaml."""
        if not os.path.exists(self.config_path):
            logger.warning("mcp_registry.config_not_found", path=self.config_path)
            return
        
        try:
            with open(self.config_path) as f:
                servers = yaml.safe_load(f) or {}
            
            for name, cfg in servers.items():
                if name not in self.clients:
                    self.clients[name] = MCPClient(
                        name=name,
                        url=cfg["url"],
                        headers=cfg.get("headers", {}),
                        timeout=cfg.get("timeout", 30.0),
                        sse_read_timeout=cfg.get("sse_read_timeout", 300.0),
                    )
                    logger.info("mcp_registry.discovered_from_config", name=name)
        except Exception as e:
            logger.error("mcp_registry.config_load_failed", error=str(e))

    def _discover_docker_services(self):
        """Auto-discover MCP services running in Docker."""
        # Map of known MCP service names to their URLs
        docker_services = {
            "filesystem": f"{self._mcp_profile_url}/filesystem/sse",
            "github": f"{self._mcp_profile_url}/github/sse",
            "slack": f"{self._mcp_profile_url}/slack/sse",
            "gmail": f"{self._mcp_profile_url}/gmail/sse",
            "brave": f"{self._mcp_profile_url}/brave/sse",
            "salesforce": f"{self._mcp_profile_url}/salesforce/sse",
            "notion": f"{self._mcp_profile_url}/notion/sse",
        }
        
        for name, url in docker_services.items():
            if name in self.clients:
                continue
                
            if self._check_service_available(url):
                self.clients[name] = MCPClient(
                    name=name,
                    url=url,
                    timeout=30.0,
                    sse_read_timeout=300.0,
                )
                logger.info("mcp_registry.discovered_docker_service", name=name, url=url)
            else:
                logger.debug("mcp_registry.docker_service_not_available", name=name)

    def _discover_from_mcp_profile(self):
        """Discover MCP servers from the MCP profile container."""
        # Try to fetch the list of available MCP servers from the profile
        try:
            import httpx
            response = httpx.get(f"{self._mcp_profile_url}/api/servers", timeout=5)
            if response.status_code == 200:
                servers = response.json()
                for server in servers:
                    name = server.get("name")
                    url = server.get("url")
                    if name and url and name not in self.clients:
                        self.clients[name] = MCPClient(
                            name=name,
                            url=url,
                            timeout=30.0,
                            sse_read_timeout=300.0,
                        )
                        logger.info("mcp_registry.discovered_from_profile", name=name)
        except Exception as e:
            logger.debug("mcp_registry.profile_discovery_failed", error=str(e))

    def _check_service_available(self, url: str) -> bool:
        """Check if a service is available."""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 80
            
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception:
            return False

    async def register_all_tools(self, tool_registry: ToolRegistry) -> int:
        """Connect to each MCP client, fetch tools, and register them."""
        if self._tools_registered:
            return 0
        
        await self.initialize()
        
        total_tools = 0
        for name, client in self.clients.items():
            try:
                # Try to connect
                connected = await client.connect()
                if not connected:
                    logger.warning("mcp_registry.connect_failed", server=name)
                    continue
                
                # Fetch tools
                tools = await client.list_tools()
                if not tools:
                    logger.warning("mcp_registry.no_tools", server=name)
                    continue
                
                # Register each tool
                for tool in tools:
                    wrapper = MCPToolWrapper(
                        mcp_client=client,
                        mcp_tool_name=tool.name,
                        description=tool.description or f"MCP tool: {tool.name}",
                        input_schema=tool.inputSchema or {},
                    )
                    tool_registry.register(wrapper)
                    total_tools += 1
                
                logger.info("mcp_registry.tools_registered", 
                            server=name, 
                            count=len(tools))
                            
            except Exception as e:
                logger.error("mcp_registry.registration_failed", 
                             server=name, 
                             error=str(e))
        
        self._tools_registered = True
        logger.info("mcp_registry.all_tools_registered", total=total_tools)
        return total_tools

    async def get_client_tools(self, client_name: str) -> List[Dict[str, Any]]:
        """Get tools for a specific client."""
        client = self.clients.get(client_name)
        if not client:
            return []
        
        if not client._connected:
            await client.connect()
        
        tools = await client.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tools
        ]

    async def close_all(self):
        """Close all MCP client connections."""
        for name, client in self.clients.items():
            await client.close()
        logger.info("mcp_registry.all_clients_closed")


# ─── Domain Prompts ──────────────────────────────────────────────

DOMAIN_PROMPTS: Dict[str, str] = {
    "sales": "You are a sales assistant with access to Salesforce CRM tools.",
    "marketing": "You are a marketing assistant with access to social media and analytics tools.",
    "finance": "You are a finance assistant with access to financial data tools.",
    "executive": "You are an executive assistant with access to business intelligence tools.",
    "healthcare": "You are a healthcare admin assistant with access to medical data tools.",
    "product": "You are a product assistant with access to product management tools.",
    "general": "You are a helpful assistant with access to various tools.",
}


def get_domain_prompt(domain: str) -> str:
    """Get the system prompt for a domain."""
    return DOMAIN_PROMPTS.get(domain, DOMAIN_PROMPTS["general"])