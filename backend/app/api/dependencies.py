"""
FastAPI dependency providers.

All external clients (ModelRouter, ToolRegistry, checkpointer, CogneeMemory, Redis)
are constructed once during the FastAPI lifespan and stored on ``app.state``.

Endpoints declare these as ``Depends(get_*)`` parameters so that:
- No module-level I/O happens at import time.
- Tests can import any API module without needing Redis / Qdrant / Kuzu / OpenAI.
- Swapping a client in tests requires only overriding the dependency.
"""
from fastapi import Request


def get_model_router(request: Request):
    """Return the ModelRouter initialised during lifespan startup."""
    return request.app.state.model_router


def get_tool_registry(request: Request):
    """Return the ToolRegistry initialised during lifespan startup."""
    return request.app.state.tool_registry


def get_checkpointer(request: Request):
    """Return the LangGraph checkpointer initialised during lifespan startup."""
    return request.app.state.checkpointer


def get_cognee_memory(request: Request):
    """Return the CogneeMemory instance initialised during lifespan startup."""
    return request.app.state.cognee_memory


def get_redis_client(request: Request):
    """Return the shared aioredis client initialised during lifespan startup."""
    return request.app.state.redis_client
