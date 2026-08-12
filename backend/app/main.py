import asyncio
import os
import structlog
from contextlib import asynccontextmanager
from app.tools.current_time import CurrentTimeTool
from app.tools.email_tool import EmailTool
from app.tools.calendar_tool import CalendarTool
from app.tools.document_tool import DocumentTool
from app.tools.slack_tool import SlackTool
from typing import Optional
from datetime import datetime, timezone
from app.api.history_api import router as history_router
from app.api.connectors import router as connectors_router
from app.api.sandbox_api import router as sandbox_router
from app.sandbox.persistent_manager import persistent_sandbox_manager
from app.mcp_clients.mcp_registry import MCPRegistry


from app.core import instances

import redis.asyncio as aioredis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.heartbeat_config import router as heartbeat_config_router
from app.api.tasks import router as tasks_router
from app.api.websocket_handler import websocket_endpoint
from app.api.memory_api import router as memory_api_router
from app.api.integrations import router as integrations_router
from app.core.config import settings
from app.core.proactive_scheduler import ProactiveScheduler
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.core.redis_checkpointer import RedisCheckpointer
from app.memory.cognee_setup import CogneeMemory
from app.mcp_clients.mcp_registry import MCPRegistry
from app.agents.router import DomainRouter
from app.tools.registry import ToolRegistry
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.tools.whatsapp_tool import WhatsAppTool
from app.services.captcha_solver import captcha_solver
from app.services.auth_handler import auth_handler
from app.memory.retriever_tool import MemoryRetrieverTool
from app.services.browser_automation_service import BrowserAutomationService
from app.core.context import synthai

logger = structlog.get_logger("aether.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager for managing the lifespan of the FastAPI application.
    Initializes and cleans up resources like Redis, CogneeMemory, and ProactiveScheduler.
    """
    logger.info("application.startup")

    # Initialize Redis client for checkpointer, task queue, and embedding cache
    app.state.redis_client = aioredis.from_url(settings.redis_url)
    await app.state.redis_client.ping()
    logger.info("redis.connected")

    # Initialize Kimi/DeepSeek Model Router
    app.state.model_router = KimiDeepSeekRouter()
    logger.info("model_router.initialized")

    # Initialize Redis Checkpointer (PRODUCTION-GRADE — survives restarts)
    app.state.checkpointer = RedisCheckpointer(
        redis_client=app.state.redis_client,
        namespace="aether",
        ttl_hours=24,
    )
    logger.info("checkpointer.initialized", type="redis")

    # Initialize Cognee Memory (with Redis embedding cache)
    app.state.cognee_memory = CogneeMemory(config={
        "qdrant_host": os.getenv("QDRANT_HOST", "qdrant"),
        "qdrant_port": int(os.getenv("QDRANT_PORT", "6333")),
        "kuzu_db_path": os.getenv("KUZU_DB_PATH", "/tmp/aether/kuzu.db"),
        "embedding_model_name": os.getenv("OPENAI_EMBEDDING_MODEL", "nvidia/nv-embed-v1"),
        "llm_extraction_model_name": os.getenv("OPENAI_CHAT_MODEL", "meta/llama-3.3-70b-instruct"),
        "redis_url": settings.redis_url,
    })
    await app.state.cognee_memory.initialize()
    logger.info("cognee_memory.initialized")

    # Initialize Browser Automation Service
    app.state.browser_service = BrowserAutomationService()
    await app.state.browser_service.start()
    logger.info("browser_service.initialized")

    # ------------------- TOOL REGISTRY & MCP -------------------
    app.state.tool_registry = ToolRegistry()
    app.state.tool_registry.register(BrowserTool())
    app.state.tool_registry.register(PythonREPLTool())
    app.state.tool_registry.register(WhatsAppTool())
    app.state.tool_registry.register(MemoryRetrieverTool(app.state.cognee_memory))
    app.state.tool_registry.register(CurrentTimeTool())
    app.state.tool_registry.register(EmailTool())
    app.state.tool_registry.register(CalendarTool())
    app.state.tool_registry.register(DocumentTool())
    app.state.tool_registry.register(SlackTool())
    logger.info("builtin_tools.registered", count=len(app.state.tool_registry.list_tools()))

    app.state.mcp_registry = MCPRegistry()
    app.state.mcp_registry = MCPRegistry()
    await app.state.mcp_registry.initialize()
    await app.state.mcp_registry.register_all_tools(app.state.tool_registry)
    logger.info("mcp_tools.registered")

    app.state.domain_router = DomainRouter(
        model_router=app.state.model_router,
        mcp_registry=app.state.mcp_registry
    )
    logger.info("domain_router.initialized")

    # ------------------- PROACTIVE SCHEDULER -------------------
    app.state.proactive_scheduler = ProactiveScheduler(
        model_router=app.state.model_router,
        cognee_memory=app.state.cognee_memory,
        redis_client=app.state.redis_client,
        briefing_time_str=os.getenv("MORNING_BRIEFING_TIME", "08:00")
    )
    asyncio.create_task(app.state.proactive_scheduler.start())
    logger.info("proactive_scheduler.started")

    # ------------------- POPULATE GLOBAL CONTEXT -------------------
    # THIS IS THE KEY CHANGE - one initialization to rule them all
    synthai.initialize(
        redis_client=app.state.redis_client,
        model_router=app.state.model_router,
        checkpointer=app.state.checkpointer,
        cognee_memory=app.state.cognee_memory,
        browser_service=app.state.browser_service,
        tool_registry=app.state.tool_registry,
        mcp_registry=app.state.mcp_registry,
        domain_router=app.state.domain_router,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    logger.info("synthai_context.initialized")

    # Initialize persistent sandbox manager
    await persistent_sandbox_manager.initialize()
    logger.info("persistent_sandbox.initialized")

    # Store in app state
    app.state.persistent_sandbox_manager = persistent_sandbox_manager

    # Also update legacy instances for backward compatibility
    instances.tool_registry = app.state.tool_registry
    instances.mcp_registry = app.state.mcp_registry
    instances.domain_router = app.state.domain_router
    instances.model_router = app.state.model_router
    instances.checkpointer = app.state.checkpointer
    instances.cognee_memory = app.state.cognee_memory

    yield

    # ------------------- CLEANUP -------------------
    logger.info("application.shutdown")
    
    # Use synthai.close() for unified cleanup
    await synthai.close()
    
    # Also clean up proactive scheduler separately (it's not in synthai)
    if hasattr(app.state, 'proactive_scheduler'):
        await app.state.proactive_scheduler.stop()
        logger.info("proactive_scheduler.stopped")
    
    if hasattr(app.state, 'mcp_registry'):
        await app.state.mcp_registry.close_all()
        logger.info("mcp_registry.closed")
    
    logger.info("application.shutdown_complete")


app = FastAPI(
    lifespan=lifespan,
    title="Aether Autonomous Agent Backend",
    description="Backend for the Aether autonomous agent, featuring memory, planning, and execution capabilities.",
    version="0.1.0"
)

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
app.include_router(integrations_router)
app.include_router(history_router)
app.include_router(sandbox_router)
app.include_router(connectors_router)  # New connectors API router

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_route(websocket: WebSocket):
    await websocket_endpoint(
        websocket,
        cognee_memory=app.state.cognee_memory,
        checkpointer=app.state.checkpointer,
        model_router=app.state.model_router,
        browser_service=app.state.browser_service,
        tool_registry=app.state.tool_registry,
        domain_router=app.state.domain_router
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