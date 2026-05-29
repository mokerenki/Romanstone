"""
Aether — FastAPI Entry Point
Bootstraps the full application with Phase 0/1/2 modules.
"""

from fastapi import FastAPI, APIRouter, Request
from fastapi.responses import JSONResponse
import os
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
        "phases": {"0": "complete"},
        "env_check": {
            "kimi_key_set": bool(os.getenv("KIMI_API_KEY")),
            "deepseek_key_set": bool(os.getenv("DEEPSEEK_API_KEY"))
        }
    }

app.include_router(root_router, prefix="/api")

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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # This prevents the "Internal Server Error" plain text response
    print(f"ERROR: {type(exc).__name__}: {str(exc)}")
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )

# ---------------------------------------------------------------
# 4. Tool registration (must happen before routers are used)
# ---------------------------------------------------------------
from app.tools.registry import ToolRegistry
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool

from app.api import tasks
#tasks._registry.register(BrowserTool())
#tasks._registry.register(PythonREPLTool())

# ---------------------------------------------------------------
# 5. Include API routers
# ---------------------------------------------------------------
#from app.api import tasks, heartbeat_config, rbac

app.include_router(tasks.router, prefix="/api/v1")
#app.include_router(heartbeat_config.router, prefix="/api")
#app.include_router(rbac.router, prefix="/api")