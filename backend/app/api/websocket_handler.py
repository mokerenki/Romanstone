import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator
import traceback

import structlog
from langchain_core.messages import HumanMessage

# Import necessary components from your application
from app.graph import create_graph
# from app.core.config import CONFIG # Not directly used here, but good to know it's available
# from app.core.model_router import ModelRouter # Passed as argument
# from app.tools.registry import ToolRegistry # Passed as argument

logger = structlog.get_logger("aether.websocket_handler")

async def stream_task_events(
    user_message: str,
    user_id: str,
    tenant_id: str,
    thread_id: str,
    checkpointer: Any,
    model_router: Any,
    tool_registry: Any,
) -> AsyncGenerator[Dict[str, Any], None]:
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # Create the graph instance for this task
    graph = create_graph(model_router, tool_registry, checkpointer)

    initial_state = {
        "task_id": task_id,
        "task": user_message,
        "user_id": user_id,
        "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [],
        "current_step_index": 0, # Ensure this matches what executor.py expects
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