"""Global instances shared across the application."""
from typing import Optional
from app.tools.registry import ToolRegistry
from app.mcp_clients.mcp_registry import MCPRegistry
from app.agents.router import DomainRouter
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.core.redis_checkpointer import RedisCheckpointer

tool_registry: Optional[ToolRegistry] = None
mcp_registry: Optional[MCPRegistry] = None
domain_router: Optional[DomainRouter] = None
model_router: Optional[KimiDeepSeekRouter] = None
checkpointer: Optional[RedisCheckpointer] = None