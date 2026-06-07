from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from app.tools.registry import BaseTool, ToolSchema
from app.memory.cognee_setup import CogneeMemory

logger = structlog.get_logger("aether.memory.retriever_tool")

class MemoryRetrieverTool(BaseTool):
    """Tool callable by the Executor node for memory access (semantic, graph, temporal queries)."""

    def __init__(self, cognee_memory: CogneeMemory):
        super().__init__()
        self.cognee_memory = cognee_memory
        logger.info("memory_retriever_tool.initialized")

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="memory_retriever",
            description="Retrieve information from the agent\'s memory using semantic search, graph queries, or temporal queries. Use this tool to get context, facts, or relationships from the agent\'s long-term memory.",
            parameters={
                "mode": {"type": "string", "enum": ["semantic", "graph", "temporal"], "description": "The type of memory retrieval to perform: \'semantic\' for vector search, \'graph\' for Cypher queries, or \'temporal\' for time-aware fact retrieval."},
                "query": {"type": "string", "description": "The query string. For \'semantic\' mode, this is natural language. For \'graph\' mode, this is a Cypher query. For \'temporal\' mode, this is the property name to retrieve."},
                "entity_label": {"type": "string", "description": "Required for \'temporal\' mode: The label of the entity (e.g., \'Case\', \'Document\').", "optional": True},
                "entity_id": {"type": "string", "description": "Required for \'temporal\' mode: The ID of the entity (e.g., \'CASE-2023-001\').", "optional": True},
                "query_time": {"type": "string", "description": "Required for \'temporal\' mode: The timestamp (ISO 8601 format, e.g., \'2023-10-27T10:00:00Z\') at which to query the property\'s value.", "optional": True},
                "top_k": {"type": "integer", "description": "Optional: Number of top results for semantic search. Defaults to 5.", "optional": True},
            },
            required=["mode", "query"]
        )

    async def execute(self, mode: str, query: str, entity_label: Optional[str] = None, entity_id: Optional[str] = None, query_time: Optional[str] = None, top_k: int = 5) -> Dict[str, Any]:
        """Executes a memory retrieval operation based on the specified mode."""
        logger.info("memory_retriever_tool.execute", mode=mode, query=query, entity_id=entity_id, query_time=query_time)

        try:
            if mode == "semantic":
                return await self.cognee_memory.search(query, mode="semantic", top_k=top_k)
            elif mode == "graph":
                return await self.cognee_memory.search(query, mode="graph")
            elif mode == "temporal":
                if not entity_label or not entity_id or not query_time:
                    raise ValueError("entity_label, entity_id, and query_time are required for temporal mode.")
                try:
                    parsed_query_time = datetime.fromisoformat(query_time.replace("Z", "+00:00")) # Handle Z for UTC
                except ValueError:
                    raise ValueError("Invalid query_time format. Must be ISO 8601 string (e.g., 2023-10-27T10:00:00Z).")
                
                # For temporal mode, the 'query' parameter is used as 'property_name'
                return await self.cognee_memory.search(
                    query=query, # This is the property_name for temporal search
                    mode="temporal", 
                    entity_label=entity_label,
                    entity_id=entity_id, 
                    query_time=parsed_query_time
                )
            else:
                raise ValueError(f"Unsupported memory retrieval mode: {mode}")
        except Exception as e:
            logger.error("memory_retriever_tool.execution_failed", mode=mode, query=query, error=str(e), exc_info=True)
            return {"status": "error", "message": f"Failed to retrieve memory: {str(e)}"}