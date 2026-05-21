"""Aether — FastAPI Entry Point

Bootstraps the full application with Phase 0/1/2 modules.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import tasks, heartbeat_config, rbac

app = FastAPI(title="Aether", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Phase 0: Core agent loop
app.include_router(tasks.router, prefix="/api")

# Phase 1: Heartbeat configuration
app.include_router(heartbeat_config.router, prefix="/api")

# Phase 2: RBAC
app.include_router(rbac.router, prefix="/api")

@app.get("/")
async def root():
    return {"name": "Aether", "version": "0.1.0", "phases": {"0": "complete", "1": "scaffolded", "2": "scaffolded"}}
