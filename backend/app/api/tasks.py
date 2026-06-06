"""Tasks API — Phase 0 (COMPLETE)

REST endpoints for task invocation and WebSocket streaming.
"""

import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from starlette.websockets import WebSocketDisconnect # Add this import

import structlog
from fastapi import APIRouter, Depends, WebSocket # Remove WebSocketDisconnect from here
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.api.websocket_handler import stream_task_events # Add this import

from app.core.config import CONFIG
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry

logger = structlog.get_logger("aether.api")
router = APIRouter()

# Lazy init (replace with Postgres checkpointer in production)
_checkpointer = MemorySaver()
_router = ModelRouter()
_registry = ToolRegistry()  # TODO: populate with actual tools
_registry.register(BrowserTool())
_registry.register(PythonREPLTool())


@router.get("/health")
async def health():
    return {"status": "healthy", "phase": "0"}


@router.post("/tasks")
async def create_task(request: Dict[str, Any]):
    """Synchronous task execution (non-streaming)."""
    user_message = request.get("message", "")
    user_id = request.get("user_id", "anonymous")
    tenant_id = request.get("tenant_id", "default")
    thread_id = request.get("thread_id") or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    from app.graph import create_graph

    graph = create_graph(_router, _registry, _checkpointer)

    initial_state = {
        "task_id": task_id,"task": user_message, "user_id": user_id, "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [], "current_step": 0, "tool_calls": [],
        "verification": None, "needs_replan": False, "final_answer": None,
        "status": "pending", "cost_metrics": {
            "kimi_input_tokens": 0, "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0, "tool_calls": 0,
        },
        "planning_iterations": 0, "scratchpad": "",
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
                    user_message, user_id, tenant_id, thread_id,
                    _checkpointer, _router, _registry
                ):
                    await websocket.send_json(event)
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as e:
        logger.exception("websocket_error", client_id=client_id, error=str(e))
        await websocket.send_json({"type": "error", "message": str(e)})