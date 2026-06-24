import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator
import traceback

import structlog
from fastapi import WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage

from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.memory.cognee_setup import CogneeMemory
from app.memory.retriever_tool import MemoryRetrieverTool
from app.services.browser_automation_service import BrowserAutomationService
from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool
from app.tools.registry import ToolRegistry
from app.graph import create_graph

logger = structlog.get_logger("aether.websocket_handler")

async def stream_task_events(
    user_message: str,
    user_id: str,
    tenant_id: str,
    thread_id: str,
    checkpointer: Any,
    model_router: KimiDeepSeekRouter,
    browser_service: BrowserAutomationService,
    tool_registry: ToolRegistry,
) -> AsyncGenerator[Dict[str, Any], None]:
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Create the graph instance for this task
    graph = create_graph(model_router, tool_registry, checkpointer)

    # Potential integration point for browser service in the future
    if browser_service:
        # Example: TODO wire browser_service into the tool registry or task context
        logger.debug("websocket_handler.browser_service_available")

    initial_state = {
        "task_id": task_id,
        "task": user_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [],
        "current_step": 0, # Ensure this matches what executor.py expects
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
        "scratchpad": "",
    }

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "aether"}}

    # Send initial task start event
    yield {"type": "task_start", "task_id": task_id, "message": user_message, "timestamp": now}

    try:
        # Astream the graph execution
        async for event in graph.astream(initial_state, config=config):
            # LangGraph events come as a dictionary with a single key representing the node name
            # or '__end__' for the final state.
            event_type = list(event.keys())[0]
            node_output = event[event_type]

            # Customize event types for frontend consumption
            if event_type == "planner":
                yield {"type": "planner_output", "content": node_output.get("plan"), "timestamp": datetime.now(timezone.utc).isoformat()}
            elif event_type == "executor":
                # Executor output contains results from steps
                results = node_output.get("results", [])
                if results:
                    last_result = results[-1]
                    yield {"type": "executor_output", "content": last_result, "timestamp": datetime.now(timezone.utc).isoformat()}
            elif event_type == "verifier":
                yield {"type": "verifier_output", "content": node_output, "timestamp": datetime.now(timezone.utc).isoformat()}
            elif event_type == "__end__":
                final_state = node_output
                yield {
                    "type": "task_complete",
                    "task_id": final_state["task_id"],
                    "status": final_state["status"],
                    "final_answer": final_state.get("final_answer"),
                    "plan": final_state.get("plan"),
                    "verification": final_state.get("verification"),
                    "cost_metrics": final_state.get("cost_metrics"),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
            else:
                # For any other unexpected events, send them as raw graph events
                logger.debug("unknown_graph_event", event=event)
                yield {"type": "raw_graph_event", "content": event, "timestamp": datetime.now(timezone.utc).isoformat()}

    except Exception as exc:
        logger.exception("websocket_task_execution_failed", error=str(exc))
        yield {
            "type": "task_error",
            "error": str(exc),
            "trace": traceback.format_exc().splitlines()[-5:],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


async def websocket_endpoint(
    websocket: WebSocket,
    cognee_memory: CogneeMemory,
    checkpointer: Any,
    model_router: KimiDeepSeekRouter,
    browser_service: BrowserAutomationService,
):
    await websocket.accept()
    client_id = str(uuid.uuid4())
    logger.info("websocket.connected", client_id=client_id)

    tool_registry = ToolRegistry()
    tool_registry.register(BrowserTool())
    tool_registry.register(PythonREPLTool())
    tool_registry.register(MemoryRetrieverTool(cognee_memory))

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "run_task":
                user_message = data.get("message", "")
                user_id = data.get("user_id", "anonymous")
                tenant_id = data.get("tenant_id", "default")
                thread_id = data.get("thread_id") or str(uuid.uuid4())

                async for event in stream_task_events(
                    user_message,
                    user_id,
                    tenant_id,
                    thread_id,
                    checkpointer,
                    model_router,
                    browser_service,
                    tool_registry,
                ):
                    await websocket.send_json(event)
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as exc:
        logger.exception("websocket.error", client_id=client_id, error=str(exc))
        await websocket.send_json({"type": "error", "message": str(exc)})
