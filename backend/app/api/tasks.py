"""
Tasks API - Enterprise task management for SynthAI.

Design decisions:
1. NO module-level state (everything comes from synthai context)
2. ALL task state in Redis (survives restarts)
3. SINGLE source of truth for tools/config
4. Multi-worker safe (Redis handles coordination)
5. Cost tracking per task + per tenant
"""

import json
import uuid
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from starlette.websockets import WebSocketDisconnect

from app.core.context import synthai
from app.core.exceptions import ToolConfirmationRequired
from app.core.persistence import (
    persist_task_progress,
    get_task_progress,
    get_task_metadata,
    set_task_metadata
)
from app.graph import create_graph
from app.api.websocket_handler import stream_task_events

logger = structlog.get_logger("synthai.api.tasks")
router = APIRouter()

# Constants only - no state
TASK_STATUS_PREFIX = "synthai:task:status"
TASK_PROGRESS_PREFIX = "synthai:task:progress"
TASK_TTL_SECONDS = 86400  # 24 hours


# ─── Helper Functions ─────────────────────────────────────

def _get_context():
    """Get the SynthAI context. Raises clear error if not initialized."""
    synthai.ensure_initialized()
    return synthai


# ─── Endpoints ────────────────────────────────────────────

@router.get("/health")
async def health():
    """Health check that verifies context initialization."""
    try:
        synthai.ensure_initialized()
        await synthai.redis_client.ping()
        return {
            "status": "healthy",
            "context_initialized": True,
            "started_at": synthai.started_at,
        }
    except Exception as e:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "error": str(e)}
        )


@router.post("/tasks")
async def create_task(request: Dict[str, Any], background_tasks: BackgroundTasks):
    """
    Enterprise task creation with:
    - Immediate 202 response
    - Background execution
    - Cost tracking
    - Tenant isolation
    """
    user_message = request.get("message", "").strip()
    if not user_message:
        return JSONResponse(status_code=400, content={"detail": "message is required"})
    
    ctx = _get_context()
    task_id = str(uuid.uuid4())
    thread_id = request.get("thread_id") or str(uuid.uuid4())
    user_id = request.get("user_id", "anonymous")
    tenant_id = request.get("tenant_id", "default")
    
    # Store initial task metadata in Redis
    await set_task_metadata(task_id, {
        "task_id": task_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "status": "queued",
        "task": user_message,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    
    # Queue background execution
    background_tasks.add_task(
        _execute_task,
        task_id=task_id,
        user_message=user_message,
        user_id=user_id,
        tenant_id=tenant_id,
        thread_id=thread_id,
    )
    
    return {
        "task_id": task_id,
        "thread_id": thread_id,
        "status": "queued",
        "message": "Task accepted. Poll /tasks/{task_id}/status for progress.",
    }


@router.get("/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """Get task status from Redis. Works across restarts."""
    metadata = await get_task_metadata(task_id)
    if not metadata:
        return JSONResponse(status_code=404, content={"detail": "Task not found"})
    
    # Also fetch latest progress
    ctx = _get_context()
    thread_id = metadata.get("thread_id")
    if thread_id:
        progress_key = f"{TASK_PROGRESS_PREFIX}:{thread_id}"
        progress = await ctx.redis_client.hgetall(progress_key)
        if progress:
            for k, v in progress.items():
                key = k.decode() if isinstance(k, bytes) else k
                value = v.decode() if isinstance(v, bytes) else v
                if key in ("plan", "results", "cost_metrics"):
                    try:
                        metadata[key] = json.loads(value)
                    except:
                        metadata[key] = value
                else:
                    metadata[key] = value
    
    return metadata


@router.get("/api/tasks/history")
async def list_task_history(limit: int = 20):
    """List recent tasks from checkpointer."""
    ctx = _get_context()
    pattern = f"{ctx.checkpointer.namespace}:checkpoint:*"
    keys = await ctx.redis_client.keys(pattern)
    
    threads = []
    seen = set()
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        parts = key_str.split(":")
        if len(parts) < 3:
            continue
        thread_id = parts[2]
        if thread_id in seen:
            continue
        seen.add(thread_id)
        
        config = {"configurable": {"thread_id": thread_id}}
        cp = await ctx.checkpointer.aget_tuple(config)
        if cp:
            values = cp.checkpoint.get("channel_values", {})
            threads.append({
                "thread_id": thread_id,
                "task": values.get("task", "Unknown"),
                "status": values.get("status", "unknown"),
                "final_answer": values.get("final_answer"),
                "timestamp": cp.checkpoint.get("ts"),
                "cost_metrics": values.get("cost_metrics"),
            })
    
    threads.sort(key=lambda x: x.get("timestamp") or "", reverse=True)
    return {"threads": threads[:limit], "total": len(threads)}


@router.post("/agent/tools/memory_retriever")
async def memory_retriever(request: Dict[str, Any]):
    """Memory retrieval endpoint using the shared tool registry."""
    ctx = _get_context()
    
    mode = request.get("mode")
    query = request.get("query")
    entity_label = request.get("entity_label")
    entity_id = request.get("entity_id")
    query_time = request.get("query_time")
    top_k = request.get("top_k", 5)
    
    if not mode or not query:
        return JSONResponse(status_code=400, content={"error": "Both 'mode' and 'query' are required."})
    
    # Use the memory retriever from the shared tool registry
    tool = ctx.tool_registry.get("memory_retriever")
    if not tool:
        return JSONResponse(status_code=500, content={"error": "Memory retriever tool not available"})
    
    try:
        result = await tool.execute(
            mode=mode,
            query=query,
            entity_label=entity_label,
            entity_id=entity_id,
            query_time=query_time,
            top_k=int(top_k) if top_k is not None else 5,
        )
        return result
    except Exception as exc:
        logger.exception("memory_retriever.failed", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "Memory retrieval failed.", "details": str(exc)})


# ─── Background Task Execution ──────────────────────────

async def _execute_task(
    task_id: str,
    user_message: str,
    user_id: str,
    tenant_id: str,
    thread_id: str,
):
    """Execute task with state management."""
    ctx = _get_context()
    
    await set_task_metadata(task_id, {
        "task_id": task_id,
        "thread_id": thread_id,
        "status": "running",
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    
    graph = create_graph(
        ctx.model_router,
        ctx.domain_router,
        ctx.tool_registry,
        ctx.checkpointer
    )
    
    initial_state = {
        "task_id": task_id,
        "task": user_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [],
        "current_step": 0,
        "results": [],
        "tool_calls": [],
        "verification": None,
        "needs_replan": False,
        "final_answer": None,
        "status": "pending",
        "cost_metrics": {
            "kimi_input_tokens": 0, "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0, "tool_calls": 0,
        },
        "planning_iterations": 0,
        "confirmed_tools": {},
        "skipped_steps": {},
    }
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        async for event in graph.astream(initial_state, config=config):
            event_type = list(event.keys())[0]
            node_output = event[event_type]
            await persist_task_progress(thread_id, node_output)
        
        snapshot = await graph.aget_state(config)
        final_state = snapshot.values if snapshot else initial_state
        
        await set_task_metadata(task_id, {
            "task_id": task_id,
            "thread_id": thread_id,
            "status": final_state.get("status", "completed"),
            "final_answer": final_state.get("final_answer"),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "cost_metrics": json.dumps(final_state.get("cost_metrics", {})),
        })
        
    except ToolConfirmationRequired as e:
        await set_task_metadata(task_id, {
            "task_id": task_id,
            "thread_id": thread_id,
            "status": "awaiting_confirmation",
            "pending_confirmation": json.dumps({
                "tool_name": e.tool_name,
                "tool_args": e.tool_args,
                "step_description": e.step_description,
                "step_index": e.step_index,
            }),
        })
        
    except Exception as e:
        await set_task_metadata(task_id, {
            "task_id": task_id,
            "thread_id": thread_id,
            "status": "failed",
            "error": str(e),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.exception("task_execution_failed", task_id=task_id)


# ─── WebSocket Endpoint ──────────────────────────────────

@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    """WebSocket endpoint with shared context."""
    await websocket.accept()
    logger.info("websocket.connected", client_id=client_id)
    
    try:
        ctx = _get_context()
        
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            
            if action == "run_task":
                user_message = data.get("message", "").strip()
                
                # Validate message
                if not user_message:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Please enter a message before running a task.",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                
                user_id = data.get("user_id", "anonymous")
                tenant_id = data.get("tenant_id", "default")
                thread_id = data.get("thread_id") or str(uuid.uuid4())
                
                async for event in stream_task_events(
                    user_message=user_message,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    checkpointer=ctx.checkpointer,
                    model_router=ctx.model_router,
                    tool_registry=ctx.tool_registry,
                    domain_router=ctx.domain_router,
                    browser_service=ctx.browser_service,
                ):
                    await websocket.send_json(event)
                    
            elif action == "confirm_tool":
                thread_id = data.get("thread_id")
                tool_name = data.get("tool_name")
                step_index = data.get("step_index")
                if not thread_id or not tool_name:
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id and tool_name are required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                    
                async for event in stream_task_events(
                    data.get("message", ""),
                    data.get("user_id", "anonymous"),
                    data.get("tenant_id", "default"),
                    thread_id,
                    ctx.checkpointer,
                    ctx.model_router,
                    ctx.tool_registry,
                    ctx.domain_router,
                    ctx.browser_service,
                    extra_state={"confirmed_tools": {tool_name: True}},
                ):
                    await websocket.send_json(event)
                    
            elif action == "reject_tool":
                thread_id = data.get("thread_id")
                step_index = data.get("step_index")
                if not thread_id or step_index is None:
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id and step_index are required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                    
                async for event in stream_task_events(
                    data.get("message", ""),
                    data.get("user_id", "anonymous"),
                    data.get("tenant_id", "default"),
                    thread_id,
                    ctx.checkpointer,
                    ctx.model_router,
                    ctx.tool_registry,
                    ctx.domain_router,
                    ctx.browser_service,
                    extra_state={"skipped_steps": {step_index: True}},
                ):
                    await websocket.send_json(event)
                    
            elif action == "resume_task":
                thread_id = data.get("thread_id")
                if not thread_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id is required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                    
                async for event in stream_task_events(
                    data.get("message", ""),
                    data.get("user_id", "anonymous"),
                    data.get("tenant_id", "default"),
                    thread_id,
                    ctx.checkpointer,
                    ctx.model_router,
                    ctx.tool_registry,
                    ctx.domain_router,
                    ctx.browser_service,
                ):
                    await websocket.send_json(event)
                    
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
                
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as e:
        logger.exception("websocket_error", client_id=client_id, error=str(e))
        await websocket.send_json({
            "type": "error",
            "message": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })


# ─── Proactive Task Queue ──────────────────────────────

async def create_proactive_task_to_queue(
    task_description: str,
    context: str = "",
    user_id: str = "heartbeat",
    tenant_id: str = "default",
    priority: str = "medium",
    action_type: str = "proactive_monitoring",
) -> Dict[str, Any]:
    """Dispatch proactive task to Redis Stream."""
    ctx = _get_context()
    
    task_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    task_payload = {
        "task_id": task_id,
        "thread_id": thread_id,
        "task_description": task_description,
        "context": context,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "priority": priority,
        "action_type": action_type,
        "timestamp": now,
    }
    
    await ctx.redis_client.xadd(
        "proactive_tasks_stream",
        {"payload": json.dumps(task_payload).encode("utf-8")}
    )
    
    return {"status": "dispatched_to_queue", "task_id": task_id}