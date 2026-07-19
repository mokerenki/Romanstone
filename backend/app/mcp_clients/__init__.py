"""
MCP Registry - Central registry for all MCP modules
"""

from typing import Dict, List, Optional
from app.mcp.base_mcp import BaseMCP
from app.mcp.sales_mcp import SalesMCP
from app.mcp.marketing_mcp import MarketingMCP
from app.mcp.finance_mcp import FinanceMCP
from app.mcp.executive_mcp import ExecutiveMCP
from app.memory.cognee_setup import CogneeMemory
from app.tools.registry import ToolRegistry

class MCPRegistry:
    """Central registry for MCP modules."""
    
    def __init__(self, memory: CogneeMemory):
        self.memory = memory
        self.modules: Dict[str, BaseMCP] = {}
        self._init_modules()
    
    def _init_modules(self):
        """Initialize all MCP modules."""
        self.modules["sales"] = SalesMCP(self.memory)
        self.modules["marketing"] = MarketingMCP(self.memory)
        self.modules["finance"] = FinanceMCP(self.memory)
        self.modules["executive"] = ExecutiveMCP(self.memory)
    
    def get_module(self, domain: str) -> Optional[BaseMCP]:
        """Get MCP module by domain."""
        return self.modules.get(domain)
    
    def get_all_modules(self) -> Dict[str, BaseMCP]:
        """Get all MCP modules."""
        return self.modules
    
    def register_tools(self, registry: ToolRegistry):
        """Register all tools from all MCP modules."""
        for module in self.modules.values():
            for tool in module.get_tools():
                registry.register(tool)
    
    async def get_domain_context(self, domain: str, user_id: str, thread_id: str) -> Dict[str, Any]:
        """Get context from a specific domain."""
        module = self.get_module(domain)
        if module:
            return await module.get_context(user_id, thread_id)
        return {"error": f"Domain {domain} not found"}
    
    def get_domain_prompt(self, domain: str) -> str:
        """Get domain-specific system prompt."""
        module = self.get_module(domain)
        if module:
            return module.get_domain_prompt()
        return "You are a helpful assistant."