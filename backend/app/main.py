import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import FastAPI, APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.api.websocket_handler import stream_task_events

from app.core.config import CONFIG
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry
from app.graph import create_graph

# -------------------------------------------------------------------------------
# 1.  Redis (async) & Cognee memory
# -------------------------------------------------------------------------------
from redis.asyncio import Redis
from redis.exceptions import RedisError
from app.memory.cognee_setup import CogneeMemory
from app.memory.retriever_tool import MemoryRetrieverTool

logger = structlog.get_logger("aether.api")
router = APIRouter()          # router used for the public endpoints

# Global Redis client (created lazily during startup)
redis_client: Optional[Redis] = None

# Global Cognee memory instance – created once at import time
_cognee_memory = CogneeMemory(
    config={
        "kuzu_db_path": os.environ.get("KUZU_DB_PATH_API", "/tmp/aether_api/kuzu.db"),
        "qdrant_host": os.environ.get("QDRANT_HOST", "localhost"),
        "qdrant_port": int(os.environ.get("QDRANT_PORT", 6333)),
        "openai_api_key": os.environ.get("OPENAI_API_KEY"),
        "openai_api_base": os.environ.get("OPENAI_API_BASE"),
    }
)

# -------------------------------------------------------------------------------
# 2.  Tool registry & model router
# -------------------------------------------------------------------------------
_router = ModelRouter()
_registry = ToolRegistry()
_registry.register(BrowserTool())
_registry.register(PythonREPLTool())
_registry.register(MemoryRetrieverTool(_cognee_memory))

# -------------------------------------------------------------------------------
# 3.  Lifespan hooks – startup / shutdown
# -------------------------------------------------------------------------------
# Import the heartbeat daemon that will be started/stopped
from app.heartbeat.daemon import HeartbeatDaemon
heartbeat_daemon = HeartbeatDaemon()

# Lazy init (replace with Postgres checkpointer in production)
_checkpointer = MemorySaver()


async def get_redis_client() -> Redis:
    """Provides a globally managed Redis client instance."""
    global redis_client
    if redis_client is None:
        logger.warning(
            "redis_client.not_initialized_via_lifespan",
            message="Initializing Redis client directly. Ensure this is managed by FastAPI lifespan in production.",
        )
        redis_client = await Redis.from_url("redis://redis:6379/0")
    return redis_client


async def lifespan(app: FastAPI):
    """FastAPI lifespan callbacks."""
    logger.info("app.startup")

    # Initialise Cognee memory (and its Kuzu graph if present)
    if _cognee_memory.kuzu_graph:
        _cognee_memory.kuzu_graph.initialize()
    await _cognee_memory.initialize()
    logger.info("api_memory.initialized_successfully")

    # Start the heartbeat daemon
    await heartbeat_daemon.start()
    logger.info("heartbeat_daemon.started_successfully")

    yield  # Application runs

    logger.info("app.shutdown")
    await heartbeat_daemon.stop()
    logger.info("heartbeat_daemon.stopped_successfully")

    if redis_client:
        await redis_client.close()
        logger.info("redis.client_closed")
    # TODO: add explicit shutdown for Qdrant/Kuzu clients if they expose a close() method


# -------------------------------------------------------------------------------
# 4.  FastAPI application
# -------------------------------------------------------------------------------
app = FastAPI(lifespan=lifespan)

# -------------------------------------------------------------------------------
# 5.  Include routers
# -------------------------------------------------------------------------------
# Import the API routers that contain the public endpoints
from app.api import tasks, heartbeat_config  # <-- import the modules that expose .router

app.include_router(tasks.router, prefix="/api")
app.include_router(heartbeat_config.router, prefix="/api")
app.include_router(router)  # public endpoints defined below


# -------------------------------------------------------------------------------
# 6.  Public endpoints
# -------------------------------------------------------------------------------
@router.get("/health")
async def health():
    return {"status": "healthy", "phase": "0"}


@router.post("/tasks")
async def create_task(request: Dict[str, Any]):
    """Synchronous task execution (non‑streaming)."""
    user_message = request.get("message", "")
    user_id = request.get("user_id", "anonymous")
    tenant_id = request.get("tenant_id", "default")
    thread_id = request.get("thread_id") or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    graph = create_graph(_router, _registry, _checkpointer)

    initial_state = {
        "task_id": task_id,
        "task": user_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [],
        "current_step": 0,
        "tool_calls": [],
        "verification": None,
        "needs_replan": False,
        "final_answer": None,
        "status": "pending",
        "cost_metrics": {
            "kimi_input_tokens": 0,
            "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0,
            "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0,
            "tool_calls": 0,
        },
        "planning_iterations": 0,
        "scratchpad": "",
    }

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "aether"}}
    try:
        final_state = await graph.ainvoke(initial_state, config=config)
    except Exception as exc:
        error_trace = traceback.format_exc()
        logger.exception("task_execution_failed", error=str(exc), traceback=error_trace)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Task execution failed.",
                "error": str(exc),
                "trace": error_trace.splitlines()[-5:],
            },
        )

    return {
        "task_id": final_state["task_id"],
        "status": final_state["status"],
        "final_answer": final_state.get("final_answer"),
        "plan": final_state.get("plan"),
        "verification": final_state.get("verification"),
        "cost_metrics": final_state.get("cost_metrics"),
    }


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await websocket.accept()
    logger.info("websocket.connected", client_id=client_id)
    try:
        while True:
            data = await websocket.receive_json()
            if data.get("action") == "run_task":
                user_message = data.get("message", "")
                user_id = data.get("user_id", "anonymous")
                tenant_id = data.get("tenant_id", "default")
                thread_id = data.get("thread_id") or str(uuid.uuid4())

                async for event in stream_task_events(
                    user_message,
                    user_id,
                    tenant_id,
                    thread_id,
                    _checkpointer,
                    _router,
                    _registry,
                ):
                    await websocket.send_json(event)
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as e:
        logger.exception("websocket_error", client_id=client_id, error=str(e))
        await websocket.send_json({"type": "error", "message": str(e)})
