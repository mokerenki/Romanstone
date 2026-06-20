import asyncio
import os
import structlog
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from app.api.heartbeat_config import router as heartbeat_config_router
from app.api.tasks import router as tasks_router
from app.api.memory_api import router as memory_api_router
from app.core.config import settings
from app.core.redis_checkpointer import RedisCheckpointer
from app.core.proactive_scheduler import ProactiveScheduler
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.memory.cognee_setup import CogneeMemory
from app.memory.retriever_tool import MemoryRetrieverTool
from app.services.browser_automation_service import BrowserAutomationService
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("aether.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Context manager for managing the lifespan of the FastAPI application.
    Initializes and cleans up resources like Redis, CogneeMemory, and ProactiveScheduler.
    """
    logger.info("application.startup")

    # Initialize Redis client for checkpointer and task queue
    app.state.redis_client = await settings.get_redis_client()
    await app.state.redis_client.ping()
    logger.info("redis.connected")

    # Initialize Kimi/DeepSeek Model Router
    app.state.model_router = KimiDeepSeekRouter()
    logger.info("model_router.initialized")

    # Initialize Cognee Memory
    app.state.cognee_memory = CogneeMemory(
        qdrant_url=settings.QDRANT_URL,
        qdrant_api_key=settings.QDRANT_API_KEY,
        kuzu_url=settings.KUZU_URL,
        llm_router=app.state.model_router
    )
    await app.state.cognee_memory.initialize()
    logger.info("cognee_memory.initialized")

    # Initialize Redis Checkpointer
    app.state.checkpointer = RedisCheckpointer(app.state.redis_client)
    logger.info("checkpointer.initialized")

    # Initialize Tool Registry — endpoints retrieve this via Depends(get_tool_registry)
    registry = ToolRegistry()
    registry.register(BrowserTool())
    registry.register(PythonREPLTool())
    registry.register(MemoryRetrieverTool(app.state.cognee_memory))
    app.state.tool_registry = registry
    logger.info("tool_registry.initialized")

    # Initialize Browser Automation Service
    app.state.browser_service = BrowserAutomationService()
    await app.state.browser_service.start()
    logger.info("browser_service.initialized")

    # Initialize Proactive Scheduler
    app.state.proactive_scheduler = ProactiveScheduler(
        model_router=app.state.model_router,
        cognee_memory=app.state.cognee_memory,
        briefing_time_str=os.getenv("MORNING_BRIEFING_TIME", "08:00")
    )
    asyncio.create_task(app.state.proactive_scheduler.start())
    logger.info("proactive_scheduler.started")

    yield

    # Cleanup on shutdown
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


app = FastAPI(lifespan=lifespan,
              title="Aether Autonomous Agent Backend",
              description="Backend for the Aether autonomous agent, featuring memory, planning, and execution capabilities.",
              version="0.1.0")

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],  # Adjust as needed for your frontend
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
 )

# Include API routers
app.include_router(heartbeat_config_router, prefix="/api")
app.include_router(tasks_router, prefix="/api")
app.include_router(memory_api_router)


@app.get("/", response_class=HTMLResponse)
async def read_root():
    return "<h1>Aether Autonomous Agent Backend</h1>"


@app.get("/api/health", tags=["monitoring"])
async def health_check():
    return {"status": "ok", "message": "Aether backend is running"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException ):
    logger.error("aether.http_exception", status_code=exc.status_code, detail=exc.detail, path=request.url.path )
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
