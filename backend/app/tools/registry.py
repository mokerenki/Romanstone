"""ToolRegistry — Phase 0 (COMPLETE) + Phase 1/2 extension hooks

MCP-inspired tool registration with JSON schema validation.
Phase 1: Add MemoryRetriever to registry.
Phase 2: Add sandbox_template field for Firecracker isolation.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import structlog

logger = structlog.get_logger("aether.tools")


@dataclass
class ToolSchema:
    name: str
    description: str
    parameters: Dict[str, Any]
    required: List[str] = field(default_factory=list)
    # Phase 2: sandbox template for isolated execution
    sandbox_template: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                "type": "object",
                "properties": self.parameters,
                "required": self.required,
            },
            "sandbox_template": self.sandbox_template,
        }


class BaseTool(ABC):
    def __init__(self):
        self.schema = self._build_schema()

    @abstractmethod
    def _build_schema(self) -> ToolSchema:
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        pass

    def validate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        missing = [r for r in self.schema.required if r not in args]
        if missing:
            raise ValueError(f"Missing required arguments: {missing}")
        return args


class ToolRegistry:
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        logger.info("tool_registry.initialized")

    def register(self, tool: BaseTool) -> "ToolRegistry":
        name = tool.schema.name
        if name in self._tools:
            logger.warning("tool_registry.overwrite", tool=name)
        self._tools[name] = tool
        logger.info("tool_registry.registered", tool=name)
        return self

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def list_tools(self) -> List[str]:
        return list(self._tools.keys())

    def describe_all(self) -> List[Dict[str, Any]]:
        return [tool.schema.to_dict() for tool in self._tools.values()]

    def unregister(self, name: str) -> None:
        if name in self._tools:
            del self._tools[name]
            logger.info("tool_registry.unregistered", tool=name)
