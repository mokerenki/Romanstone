import asyncio
import os
import structlog
from contextlib import asynccontextmanager
from typing import Optional

from app.core import instances

instances.tool_registry = app.state.tool_registry
instances.mcp_registry = app.state.mcp_registry
instances.domain_router = app.state.domain_router
instances.model_router = app.state.model_router
instances.checkpointer = app.state.checkpointer


import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.heartbeat_config import router as heartbeat_config_router
from app.api.tasks import router as tasks_router
from app.api.websocket_handler import websocket_endpoint
from app.api.memory_api import router as memory_api_router
from app.core.config import settings
from app.core.redis_checkpointer import RedisCheckpointer
from app.core.proactive_scheduler import ProactiveScheduler
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.memory.cognee_setup import CogneeMemory
from app.mcp_clients.mcp_registry import MCPRegistry
from app.agents.router import DomainRouter
from app.tools.registry import ToolRegistry
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.tools.whatsapp_tool import WhatsAppTool
from app.memory.retriever_tool import MemoryRetrieverTool
from app.services.browser_automation_service import BrowserAutomationService

logger = structlog.get_logger("aether.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager for managing the lifespan of the FastAPI application.
    Initializes and cleans up resources like Redis, CogneeMemory, and ProactiveScheduler.
    """
    logger.info("application.startup")

    # Initialize Redis client for checkpointer and task queue
    app.state.redis_client = aioredis.from_url(settings.redis_url)
    await app.state.redis_client.ping()
    logger.info("redis.connected")

    # Initialize Kimi/DeepSeek Model Router
    app.state.model_router = KimiDeepSeekRouter()
    logger.info("model_router.initialized")

    # Initialize Cognee Memory
    app.state.cognee_memory = CogneeMemory(config={
        "qdrant_host": os.getenv("QDRANT_HOST", "qdrant"),
        "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
        "kuzu_db_path": os.getenv("KUZU_DB_PATH", "/tmp/aether/kuzu.db"),
    })
    await app.state.cognee_memory.initialize()
    memory_api_router.cognee_memory = app.state.cognee_memory
    logger.info("cognee_memory.initialized")

    # Initialize Redis Checkpointer
    app.state.checkpointer = RedisCheckpointer(app.state.redis_client)
    tasks_router.checkpointer = app.state.checkpointer
    logger.info("checkpointer.initialized")

    # Initialize Browser Automation Service
    app.state.browser_service = BrowserAutomationService()
    await app.state.browser_service.start()
    logger.info("browser_service.initialized")

    # ------------------- TOOL REGISTRY & MCP -------------------
    # 1. Create the central tool registry
    app.state.tool_registry = ToolRegistry()

    # 2. Register built-in tools
    app.state.tool_registry.register(BrowserTool())
    app.state.tool_registry.register(PythonREPLTool())
    app.state.tool_registry.register(WhatsAppTool())
    # Memory retriever needs the cognee_memory instance
    app.state.tool_registry.register(MemoryRetrieverTool(app.state.cognee_memory))
    logger.info("builtin_tools.registered")

    # 3. Initialize MCP registry and register MCP tools
    app.state.mcp_registry = MCPRegistry()
    await app.state.mcp_registry.register_all_tools(app.state.tool_registry)
    logger.info("mcp_tools.registered")

    # 4. Create Domain Router (uses model_router and mcp_registry)
    app.state.domain_router = DomainRouter(
        model_router=app.state.model_router,
        mcp_registry=app.state.mcp_registry
    )
    logger.info("domain_router.initialized")

    # ------------------- PROACTIVE SCHEDULER -------------------
    app.state.proactive_scheduler = ProactiveScheduler(
        model_router=app.state.model_router,
        cognee_memory=app.state.cognee_memory,
        briefing_time_str=os.getenv("MORNING_BRIEFING_TIME", "08:00")
    )
    asyncio.create_task(app.state.proactive_scheduler.start())
    logger.info("proactive_scheduler.started")

    yield

    # ------------------- CLEANUP -------------------
    logger.info("application.shutdown")
    if app.state.proactive_scheduler:
        await app.state.proactive_scheduler.stop()
        logger.info("proactive_scheduler.stopped")
    if app.state.browser_service:
        await app.state.browser_service.stop()
        logger.info("browser_service.stopped")
    if app.state.model_router:
        await app.state.model_router.close()
        logger.info("model_router.closed")
    if app.state.redis_client:
        await app.state.redis_client.close()
        logger.info("redis_client.closed")
    if app.state.cognee_memory:
        await app.state.cognee_memory.close()
        logger.info("cognee_memory.closed")
    if hasattr(app.state, 'mcp_registry'):
        await app.state.mcp_registry.close_all()
        logger.info("mcp_registry.closed")


app = FastAPI(lifespan=lifespan,
              title="Aether Autonomous Agent Backend",
              description="Backend for the Aether autonomous agent, featuring memory, planning, and execution capabilities.",
              version="0.1.0")

# CORS Middleware
cors_origins = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://localhost:8000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Include API routers
app.include_router(heartbeat_config_router)
app.include_router(tasks_router)
app.include_router(memory_api_router)

# WebSocket endpoint – now passes tool_registry as well
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    await websocket_endpoint(
        websocket,
        cognee_memory=app.state.cognee_memory,
        checkpointer=app.state.checkpointer,
        model_router=app.state.model_router,
        browser_service=app.state.browser_service,
        tool_registry=app.state.tool_registry,   # <-- NEW
        domain_router=app.state.domain_router    # <-- NEW (optional, can be used inside)
    )


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return "<h1>Aether Autonomous Agent Backend</h1>"


@app.get("/api/health", tags=["monitoring"])
async def health_check():
    return {"status": "ok", "message": "Aether backend is running"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    logger.error("aether.http_exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path)
    return JSONResponse(
        status_code=exc.status_code,
        content={"message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error("aether.general_exception", error=str(exc), path=request.url.path, exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"message": "An unexpected error occurred.", "detail": str(exc)},
    )