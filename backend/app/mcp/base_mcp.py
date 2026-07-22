from typing import List, Dict, Any
from abc import ABC, abstractmethod


class BaseMCP(ABC):
    """Base class for domain-specific MCP modules."""

    @abstractmethod
    def get_tools(self) -> List[Any]:
        ...

    @abstractmethod
    async def get_context(self, user_id: str, thread_id: str) -> Dict[str, Any]:
        ...

    @abstractmethod
    def get_domain_prompt(self) -> str:
        ...
