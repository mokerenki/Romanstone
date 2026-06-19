import json
import structlog
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

logger = structlog.get_logger("aether.api.memory")
router = APIRouter(prefix="/api/memory", tags=["memory"])

# This will be set during lifespan startup in main.py
cognee_memory = None

@router.post("/search")
async def search_memory(request: Dict[str, Any]):
    """
    Execute a memory search operation (semantic, graph, or temporal).
    
    Request body:
    {
        "mode": "semantic" | "graph" | "temporal",
        "query": "string",
        "entity_label": "string (optional, required for temporal)",
        "entity_id": "string (optional, required for temporal)",
        "query_time": "ISO 8601 timestamp (optional, required for temporal)",
        "top_k": "integer (optional, default 5 for semantic)"
    }
    """
    if cognee_memory is None:
        logger.error("memory_api.cognee_memory_not_initialized")
        raise HTTPException(status_code=500, detail="Memory service not initialized")

    mode = request.get("mode")
    query = request.get("query")
    entity_label = request.get("entity_label")
    entity_id = request.get("entity_id")
    query_time = request.get("query_time")
    top_k = request.get("top_k", 5)

    if not mode or not query:
        logger.warning("memory_api.missing_required_params", mode=mode, query=query)
        raise HTTPException(status_code=400, detail="Both 'mode' and 'query' are required.")

    try:
        logger.info("memory_api.search_initiated", mode=mode, query=query[:50])
        
        result = await cognee_memory.search(
            query=query,
            mode=mode,
            top_k=int(top_k) if top_k is not None else 5,
            entity_label=entity_label,
            entity_id=entity_id,
            query_time=query_time
        )
        
        logger.info("memory_api.search_completed", mode=mode, result_count=len(result.get("results", [])))
        return result
    
    except ValueError as ve:
        logger.warning("memory_api.validation_error", error=str(ve), mode=mode)
        raise HTTPException(status_code=400, detail=str(ve))
    
    except Exception as exc:
        logger.exception("memory_api.search_failed", error=str(exc), mode=mode)
        raise HTTPException(status_code=500, detail=f"Memory search failed: {str(exc)}")


@router.get("/health")
async def memory_health():
    """Health check for the memory service."""
    if cognee_memory is None:
        return JSONResponse(status_code=503, content={"status": "unavailable", "message": "Memory service not initialized"})
    
    try:
        if not cognee_memory._initialized:
            return JSONResponse(status_code=503, content={"status": "initializing", "message": "Memory service is initializing"})
        
        return {"status": "healthy", "message": "Memory service is operational"}
    except Exception as e:
        logger.error("memory_api.health_check_failed", error=str(e))
        return JSONResponse(status_code=503, content={"status": "unhealthy", "error": str(e)})


@router.post("/graph/query")
async def graph_query(request: Dict[str, Any]):
    """
    Execute a Cypher query directly against the knowledge graph.
    
    Request body:
    {
        "query": "MATCH (n) RETURN n LIMIT 10"
    }
    """
    if cognee_memory is None:
        logger.error("memory_api.cognee_memory_not_initialized")
        raise HTTPException(status_code=500, detail="Memory service not initialized")

    query = request.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="'query' is required.")

    try:
        logger.info("memory_api.graph_query_initiated", query=query[:50])
        
        result = await cognee_memory.search(query=query, mode="graph")
        
        logger.info("memory_api.graph_query_completed", result_count=len(result.get("results", [])))
        return result
    
    except Exception as exc:
        logger.exception("memory_api.graph_query_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Graph query failed: {str(exc)}")


@router.post("/ingest")
async def ingest_event(request: Dict[str, Any]):
    """
    Manually ingest an event into memory.
    
    Request body:
    {
        "content": "string (required)",
        "source": "string (optional, default 'api')",
        "event_id": "string (optional, auto-generated if not provided)"
    }
    """
    if cognee_memory is None:
        logger.error("memory_api.cognee_memory_not_initialized")
        raise HTTPException(status_code=500, detail="Memory service not initialized")

    content = request.get("content")
    if not content:
        raise HTTPException(status_code=400, detail="'content' is required.")

    event = {
        "content": content,
        "source": request.get("source", "api"),
        "event_id": request.get("event_id"),
    }

    try:
        logger.info("memory_api.ingestion_initiated", source=event["source"])
        
        await cognee_memory.ingest(event)
        
        logger.info("memory_api.ingestion_completed", event_id=event.get("event_id"))
        return {"status": "success", "message": "Event ingested successfully", "event_id": event.get("event_id")}
    
    except Exception as exc:
        logger.exception("memory_api.ingestion_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Event ingestion failed: {str(exc)}")


@router.get("/stats")
async def memory_stats():
    """
    Get statistics about the memory system.
    """
    if cognee_memory is None:
        logger.error("memory_api.cognee_memory_not_initialized")
        raise HTTPException(status_code=500, detail="Memory service not initialized")

    try:
        stats = {
            "initialized": cognee_memory._initialized,
            "qdrant_collection": cognee_memory.qdrant_collection_name if cognee_memory.qdrant_client else None,
            "embedding_model": cognee_memory.embedding_model_name,
            "llm_extraction_model": cognee_memory.llm_extraction_model_name,
        }
        
        # Try to get collection info from Qdrant if available
        if cognee_memory.qdrant_client and cognee_memory._initialized:
            try:
                collection_info = cognee_memory.qdrant_client.get_collection(cognee_memory.qdrant_collection_name)
                stats["qdrant_points_count"] = collection_info.points_count
            except Exception as e:
                logger.warning("memory_api.qdrant_stats_unavailable", error=str(e))
        
        return stats
    
    except Exception as exc:
        logger.exception("memory_api.stats_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Failed to retrieve stats: {str(exc)}")
