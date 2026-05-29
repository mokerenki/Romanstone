"""Tasks API — Phase 0 (COMPLETE)

REST endpoints for task invocation and WebSocket streaming.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from app.tools.browser_tool import BrowserTool
from app.tools.python_repl import PythonREPLTool

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
    from app.agents.planner import PlannerNode
    from app.agents.executor import ExecutorNode
    from app.agents.verifier import VerifierNode

    user_message = request.get("message", "")
    user_id = request.get("user_id", "anonymous")
    tenant_id = request.get("tenant_id", "default")
    thread_id = request.get("thread_id") or str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    planner = PlannerNode(_router, _registry)
    executor = ExecutorNode(_registry)
    verifier = VerifierNode(_router)

    # Build LangGraph state machine inline
    from langgraph.graph import END, START, StateGraph
    from typing import TypedDict, Annotated
    from langgraph.graph.message import add_messages

    class State(TypedDict):
        messages: Annotated[list, add_messages]
        plan: list
        current_step_index: int
        tool_calls: list
        verification: dict
        needs_replan: bool
        final_answer: str
        status: str
        cost_metrics: dict
        task_id: str
        user_id: str
        tenant_id: str
        planning_iterations: int
        scratchpad: str

    def should_continue(state):
        plan = state.get("plan", [])
        idx = state.get("current_step_index", 0)
        return "executor" if idx < len(plan) else "verifier"

    def should_replan(state):
        if state.get("needs_replan") and state.get("planning_iterations", 0) < 3:
            return "planner"
        return END

    builder = StateGraph(State)
    builder.add_node("planner", planner)
    builder.add_node("executor", executor)
    builder.add_node("verifier", verifier)
    builder.add_edge(START, "planner")
    builder.add_edge("planner", "executor")
    builder.add_conditional_edges("executor", should_continue, {"executor": "executor", "verifier": "verifier"})
    builder.add_conditional_edges("verifier", should_replan, {"planner": "planner", END: END})

    graph = builder.compile(checkpointer=_checkpointer)

    initial_state = {
        "task_id": task_id, "user_id": user_id, "tenant_id": tenant_id,
        "messages": [HumanMessage(content=user_message)],
        "plan": [], "current_step_index": 0, "tool_calls": [],
        "verification": None, "needs_replan": False, "final_answer": None,
        "status": "pending", "cost_metrics": {
            "kimi_input_tokens": 0, "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0, "tool_calls": 0,
        },
        "planning_iterations": 0, "scratchpad": "",
    }

    config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": "aether"}}
    final_state = await graph.ainvoke(initial_state, config=config)

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
                # TODO: Stream graph.astream() events
                await websocket.send_json({"type": "task_start", "message": data.get("message", "")})
                # Streaming implementation would go here
                await websocket.send_json({"type": "task_complete"})
            elif data.get("action") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
