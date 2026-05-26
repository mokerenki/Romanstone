"""
Aether — FastAPI Entry Point
Bootstraps the full application with Phase 0/1/2 modules.
"""

from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------
# 1. Create the app and a root router
# ---------------------------------------------------------------
app = FastAPI(title="Aether", version="0.1.0")

# ---------------------------------------------------------------
# 2. Health endpoint
# ---------------------------------------------------------------
root_router = APIRouter()

@root_router.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.get("/")
async def root():
    return {
        "name": "Aether",
        "version": "0.1.0",
        "phases": {"0": "complete"}
    }

app.include_router(root_router)

# ---------------------------------------------------------------
# 3. CORS (open for development – restrict in production)
# ---------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------
# 4. Tool registration (must happen before routers are used)
# ---------------------------------------------------------------
from app.tools.registry import ToolRegistry
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool

import app.api.tasks as tasks_module
tasks_module._registry.register(BrowserTool())
tasks_module._registry.register(PythonREPLTool())

# ---------------------------------------------------------------
# 5. Include API routers
# ---------------------------------------------------------------
from app.api import tasks, heartbeat_config, rbac

app.include_router(tasks.router, prefix="/api")
app.include_router(heartbeat_config.router, prefix="/api")
app.include_router(rbac.router, prefix="/api")