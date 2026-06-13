import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog
import aioredis

from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse
import os
from fastapi.middleware.cors import CORSMiddleware


from app.api import tasks

# Initialize Heartbeat Daemon
from app.heartbeat.daemon import HeartbeatDaemon
heartbeat_daemon = HeartbeatDaemon() # ModelRouter is not directly passed here; LLM calls are internal to tasks

from app.memory.cognee_setup import CogneeMemory
from app.memory.graph_setup import KuzuGraph

logger = structlog.get_logger("aether.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manages the startup and shutdown events for the FastAPI application."""
    logger.info("app.startup")
    
    # Initialize Redis client for API routes (e.g., for create_proactive_task_to_queue)
    tasks.redis_client = await aioredis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    logger.info("redis.client_initialized")

    if tasks._cognee_memory.kuzu_graph:
        tasks._cognee_memory.kuzu_graph.initialize()
    await tasks._cognee_memory.initialize() # This will also ensure Qdrant is ready
    logger.info("api_memory.initialized_successfully")

    await heartbeat_daemon.start()
    logger.info("heartbeat_daemon.started_successfully")

    yield # Application runs

    logger.info("app.shutdown")
    await heartbeat_daemon.stop()
    logger.info("heartbeat_daemon.stopped_successfully")
    
    if tasks.redis_client:
        await tasks.redis_client.close()
        logger.info("redis.client_closed")
    
    # TODO: Add explicit shutdown for Qdrant/Kuzu clients if they have explicit close methods

app = FastAPI(lifespan=lifespan)

# ... CORS middleware setup ...

# ---------------------------------------------------------------
# 5. Include API routers
# ---------------------------------------------------------------
from app.api import tasks, heartbeat_config, rbac

app.include_router(tasks.router, prefix="/api")
app.include_router(heartbeat_config.router, prefix="/api")
# app.include_router(rbac.router, prefix="/api") # Uncomment when RBAC is ready