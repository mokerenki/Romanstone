from typing import List, Dict, Any
from app.mcp.base_mcp import BaseMCP
from app.memory.cognee_setup import CogneeMemory


class MarketingMCP(BaseMCP):
    def __init__(self, memory: CogneeMemory):
        self.memory = memory

    def get_tools(self) -> List[Any]:
        return []

    async def get_context(self, user_id: str, thread_id: str) -> Dict[str, Any]:
        return {}

    def get_domain_prompt(self) -> str:
        return "You are a marketing assistant. Help with campaigns, leads, and engagement metrics."
