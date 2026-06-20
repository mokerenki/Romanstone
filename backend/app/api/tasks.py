import json
import os
import traceback
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from starlette.websockets import WebSocketDisconnect

import structlog
from fastapi import APIRouter, Depends, WebSocket
from fastapi.responses import JSONResponse
from langchain_core.messages import HumanMessage
from langchain_core.load import dumps

from app.api.dependencies import (
    get_checkpointer,
    get_model_router,
    get_redis_client,
    get_tool_registry,
)
from app.api.websocket_handler import stream_task_events
from app.graph import create_graph
from app.state import TaskState

logger = structlog.get_logger("aether.api")
router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy", "phase": "0"}


@router.post("/tasks")
async def create_task(
    request: Dict[str, Any],
    model_router=Depends(get_model_router),
    registry=Depends(get_tool_registry),
    checkpointer=Depends(get_checkpointer),
):
    """Synchronous task execution (non-streaming)."""
    user_message = request.get("message", "")
    user_id = request.get("user_id", "anonymous")
    tenant_id = request.get("tenant_id", "default")
    thread_id = request.get("thread_id") or str(uuid.uuid4())
    task_id = str(uuid.uuid4())

    graph = create_graph(model_router, registry, checkpointer)

    initial_state: TaskState = {
        "task_id": task_id,
        "task": user_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "messages": [dumps(HumanMessage(content=user_message))],
        "plan": [],
        "current_step": 0,
        "results": [],
        "tool_calls": [],
        "feedback": "",
        "verification": None,
        "needs_replan": False,
        "done": False,
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


@router.post("/agent/tools/memory_retriever")
async def memory_retriever(
    request: Dict[str, Any],
    registry=Depends(get_tool_registry),
):
    mode = request.get("mode")
    query = request.get("query")
    entity_label = request.get("entity_label")
    entity_id = request.get("entity_id")
    query_time = request.get("query_time")
    top_k = request.get("top_k", 5)

    if not mode or not query:
        return JSONResponse(status_code=400, content={"error": "Both 'mode' and 'query' are required."})

    try:
        tool = registry.get("memory_retriever")
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


@router.post("/tasks/proactive")
async def create_proactive_task(
    request: Dict[str, Any],
    redis=Depends(get_redis_client),
):
    """Creates a proactive task and dispatches it to a Redis Stream."""
    task_description = request.get("task_description", "")
    context = request.get("context", "")
    user_id = request.get("user_id", "heartbeat")
    tenant_id = request.get("tenant_id", "default")
    priority = request.get("priority", "medium")
    action_type = request.get("action_type", "proactive_monitoring")

    task_id = str(uuid.uuid4())
    thread_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    logger.info("proactive_task.creating_and_queuing", task_id=task_id,
                task_description=task_description, priority=priority)

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

    try:
        await redis.xadd(
            "proactive_tasks_stream",
            {"payload": json.dumps(task_payload).encode("utf-8")},
        )
        logger.info("proactive_task.dispatched_to_redis_stream",
                    task_id=task_id, stream="proactive_tasks_stream")
        return {"status": "dispatched_to_queue", "task_id": task_id}
    except Exception as exc:
        error_trace = traceback.format_exc()
        logger.error("proactive_task.dispatch_failed_redis", task_id=task_id,
                     error=str(exc), traceback=error_trace, exc_info=True)
        raise


@router.websocket("/ws/{client_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    client_id: str,
    model_router=Depends(get_model_router),
    registry=Depends(get_tool_registry),
    checkpointer=Depends(get_checkpointer),
):
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
                    checkpointer, model_router, registry,
                ):
                    await websocket.send_json(event)
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as e:
        logger.exception("websocket_error", client_id=client_id, error=str(e))
        await websocket.send_json({"type": "error", "message": str(e)})
