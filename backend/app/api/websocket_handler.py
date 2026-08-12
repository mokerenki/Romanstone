import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, AsyncGenerator, Optional
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
from app.agents.router import DomainRouter
from app.mcp_clients.mcp_registry import MCPRegistry
from app.graph import create_graph
from app.core import instances
from app.core.exceptions import ToolConfirmationRequired
from app.core.errors import TaskErrorCode, to_user_error
from app.sandbox.manager import SandboxManager, set_active_sandbox_manager, set_active_task_id
from app.core.persistence import persist_task_progress
from app.core.context import synthai
from app.core.history_store import HistoryStore, EventType

logger = structlog.get_logger("aether.websocket_handler")


async def get_task_state_from_checkpoint(thread_id: str) -> Optional[dict]:
    """Retrieve the last checkpoint state for a thread."""
    ctx = synthai
    try:
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await ctx.checkpointer.aget_tuple(config)
        if snapshot:
            return snapshot.checkpoint.get("channel_values", {})
    except Exception as e:
        logger.error(f"Failed to get checkpoint for {thread_id}: {e}")
    return None


async def resume_task_from_checkpoint(
    thread_id: str,
    extra_state: Optional[dict] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Resume a task from its last checkpoint."""
    ctx = synthai
    
    state = await get_task_state_from_checkpoint(thread_id)
    if not state:
        yield {
            "type": "error",
            "message": f"No checkpoint found for thread {thread_id}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return
    
    if state.get("status") != "paused":
        yield {
            "type": "error",
            "message": f"Task {thread_id} is not paused (status: {state.get('status')})",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return
    
    if extra_state:
        state.update(extra_state)
    
    state["status"] = "running"
    state["resumed_at"] = datetime.now(timezone.utc).isoformat()
    
    graph = create_graph(
        ctx.model_router,
        ctx.domain_router,
        ctx.tool_registry,
        ctx.checkpointer
    )
    
    config = {"configurable": {"thread_id": thread_id}}
    
    try:
        async for event in graph.astream(state, config=config):
            event_type = list(event.keys())[0]
            node_output = event[event_type]
            yield {
                "type": "node_output",
                "node": event_type,
                "content": node_output,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await persist_task_progress(thread_id, node_output)
        
        snapshot = await graph.aget_state(config)
        final_state = snapshot.values if snapshot else state
        
        yield {
            "type": "task_complete",
            "status": final_state.get("status", "completed"),
            "final_answer": final_state.get("final_answer"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
    except Exception as e:
        logger.exception(f"Error resuming task {thread_id}")
        yield {
            "type": "error",
            "message": f"Error resuming task: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }


async def get_paused_task_state(thread_id: str) -> Optional[dict]:
    """Get the full state of a paused task for inspection."""
    state = await get_task_state_from_checkpoint(thread_id)
    if state and state.get("status") == "paused":
        return {
            "thread_id": thread_id,
            "task": state.get("task"),
            "plan": state.get("plan", []),
            "current_step": state.get("current_step", 0),
            "results": state.get("results", []),
            "verification": state.get("verification"),
            "cost_metrics": state.get("cost_metrics", {}),
            "final_answer": state.get("final_answer"),
            "paused_at": state.get("paused_at"),
        }
    return None


async def stream_task_events(
    user_message: str,
    user_id: str,
    tenant_id: str,
    thread_id: str,
    checkpointer: Any,
    model_router: KimiDeepSeekRouter,
    tool_registry: Optional[ToolRegistry] = None,
    domain_router: Optional[DomainRouter] = None,
    browser_service: Optional[BrowserAutomationService] = None,
    extra_state: Optional[Dict[str, Any]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Stream task execution events via WebSocket.

    Args:
        user_message: The user's task description.
        user_id: Identifier of the user.
        tenant_id: Tenant/organization identifier.
        thread_id: Conversation thread identifier.
        checkpointer: LangGraph checkpointer for persistence.
        model_router: Router for LLM model selection.
        tool_registry: Registry of available tools (uses global if None).
        domain_router: Router for domain classification (uses global if None).
        browser_service: Browser automation service (optional).
        extra_state: Additional state to merge into initial state.
    """
    task_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    sandbox_manager = SandboxManager()
    sandbox_task_id = f"task:{task_id}"

    # Use global instances if not provided
    if tool_registry is None:
        tool_registry = instances.tool_registry
    if domain_router is None:
        domain_router = instances.domain_router
    if checkpointer is None:
        checkpointer = instances.checkpointer
    if model_router is None:
        model_router = instances.model_router

    # Validate required dependencies
    if tool_registry is None or domain_router is None or checkpointer is None or model_router is None:
        logger.error("stream_task_events.missing_dependencies")
        yield {
            "type": "task_error",
            "error": "Application dependencies not fully initialized. Please try again later.",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        return

    history_store = HistoryStore()

    # Create the graph instance for this task
    graph = create_graph(model_router, domain_router, tool_registry, checkpointer)

    if browser_service:
        logger.debug("websocket_handler.browser_service_available")

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
        "scratchpad": "",
        "confirmed_tools": {},
        "skipped_steps": {},
    }
    if extra_state:
        initial_state.update(extra_state)

    config = {"configurable": {"thread_id": thread_id}}

    yield {"type": "task_start", "task_id": task_id, "message": user_message, "timestamp": now}

    try:
        await history_store.ensure_initialized()
        existing = await history_store.get_task_history(thread_id)
        if not existing:
            await history_store.create_task_record(
                thread_id=thread_id,
                task=user_message,
                user_id=user_id,
                tenant_id=tenant_id
            )
    except Exception as e:
        logger.warning("history.task_record_create_failed", error=str(e), thread_id=thread_id)

    try:
        await history_store.ensure_initialized()
        await history_store.add_event(thread_id, EventType.TASK_START, {"message": user_message})
    except Exception as e:
        logger.warning("history.task_start_event_failed", error=str(e), thread_id=thread_id)

    try:
        set_active_sandbox_manager(sandbox_manager)
        set_active_task_id(sandbox_task_id)
        initial_state["sandbox_id"] = sandbox_task_id
        
        async for event in graph.astream(initial_state, config=config):
            event_type = list(event.keys())[0]
            node_output = event[event_type]

            if event_type == "planner":
                yield {
                    "type": "planner_output", 
                    "content": node_output.get("plan"), 
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await persist_task_progress(thread_id, node_output)
                
            elif event_type == "executor":
                results = node_output.get("results", [])
                if results:
                    last_result = results[-1]
                    yield {
                        "type": "executor_output", 
                        "content": last_result, 
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                await persist_task_progress(thread_id, node_output)
                
            elif event_type == "verifier":
                yield {
                    "type": "verifier_output", 
                    "content": node_output.get("verification"), 
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                await persist_task_progress(thread_id, node_output)
                
            else:
                logger.debug("unknown_graph_event", event_type=event_type)

        snapshot = await graph.aget_state(config)
        final_state = snapshot.values if snapshot and snapshot.values else initial_state

        try:
            await history_store.ensure_initialized()
            await history_store.update_task_status(
                thread_id=thread_id,
                status=final_state.get("status", "completed"),
                final_answer=final_state.get("final_answer"),
                cost_metrics=final_state.get("cost_metrics")
            )
        except Exception as e:
            logger.warning("history.task_complete_failed", error=str(e), thread_id=thread_id)

        try:
            await history_store.ensure_initialized()
            await history_store.add_event(
                thread_id,
                EventType.TASK_COMPLETE,
                {
                    "status": final_state.get("status", "completed"),
                    "final_answer": final_state.get("final_answer"),
                }
            )
        except Exception as e:
            logger.warning("history.task_complete_event_failed", error=str(e), thread_id=thread_id)

        yield {
            "type": "task_complete",
            "task_id": final_state.get("task_id", task_id),
            "status": final_state.get("status", "completed"),
            "final_answer": final_state.get("final_answer"),
            "plan": final_state.get("plan"),
            "verification": final_state.get("verification"),
            "cost_metrics": final_state.get("cost_metrics"),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except ToolConfirmationRequired as exc:
        # Emit confirmation event and pause — client must send confirm_tool to resume
        logger.info("websocket.confirmation_required", tool=exc.tool_name, step=exc.step_index)
        try:
            await history_store.ensure_initialized()
            await history_store.update_task_status(
                thread_id=thread_id,
                status="paused"
            )
        except Exception as e:
            logger.warning("history.task_pause_failed", error=str(e), thread_id=thread_id)
        try:
            await history_store.ensure_initialized()
            await history_store.add_event(
                thread_id,
                EventType.TASK_PAUSED,
                {"tool_name": exc.tool_name, "step_index": exc.step_index}
            )
        except Exception as e:
            logger.warning("history.task_pause_event_failed", error=str(e), thread_id=thread_id)
        yield {
            "type": "needs_confirmation",
            "tool_name": exc.tool_name,
            "tool_args": exc.tool_args,
            "step_description": exc.step_description,
            "step_index": exc.step_index,
            "task_id": task_id,
            "thread_id": thread_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except Exception as exc:
        code, user_message_error = to_user_error(exc)
        logger.exception("websocket_task_execution_failed", error_code=code, error=str(exc))
        try:
            await history_store.ensure_initialized()
            await history_store.update_task_status(
                thread_id=thread_id,
                status="failed",
                error=user_message_error
            )
        except Exception as e:
            logger.warning("history.task_error_failed", error=str(e), thread_id=thread_id)
        try:
            await history_store.ensure_initialized()
            await history_store.add_event(
                thread_id,
                EventType.TASK_FAILED,
                {"error": user_message_error, "error_code": code}
            )
        except Exception as e:
            logger.warning("history.task_error_event_failed", error=str(e), thread_id=thread_id)
        yield {
            "type": "task_error",
            "error_code": code,
            "message": user_message_error,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    finally:
        set_active_sandbox_manager(None)
        set_active_task_id(None)
        await sandbox_manager.destroy(sandbox_task_id)


async def websocket_endpoint(
    websocket: WebSocket,
    cognee_memory: CogneeMemory,
    checkpointer: Any,
    model_router: KimiDeepSeekRouter,
    browser_service: BrowserAutomationService,
    tool_registry: ToolRegistry,
    domain_router: DomainRouter,
):
    """WebSocket endpoint for real-time task streaming."""
    await websocket.accept()
    client_id = str(uuid.uuid4())
    logger.info("websocket.connected", client_id=client_id)

    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            logger.debug("websocket.received", client_id=client_id, action=action)
            
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
                    user_message,
                    user_id,
                    tenant_id,
                    thread_id,
                    checkpointer,
                    model_router,
                    tool_registry,
                    domain_router,
                    browser_service,
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
                    checkpointer,
                    model_router,
                    tool_registry,
                    domain_router,
                    browser_service,
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
                    checkpointer,
                    model_router,
                    tool_registry,
                    domain_router,
                    browser_service,
                    extra_state={"skipped_steps": {step_index: True}},
                ):
                    await websocket.send_json(event)
                    
            elif action == "pause_task":
                thread_id = data.get("thread_id")
                if not thread_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id is required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                
                try:
                    ctx = synthai
                    config = {"configurable": {"thread_id": thread_id}}
                    snapshot = await ctx.checkpointer.aget_tuple(config)
                    
                    if not snapshot:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Task {thread_id} not found",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                    
                    state = snapshot.checkpoint.get("channel_values", {})
                    current_status = state.get("status", "pending")
                    
                    if current_status == "paused":
                        await websocket.send_json({
                            "type": "task_paused",
                            "thread_id": thread_id,
                            "state": state,
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                        
                    if current_status in ["completed", "failed"]:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Task {thread_id} is already {current_status}",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                    
                    state["status"] = "paused"
                    state["paused_at"] = datetime.now(timezone.utc).isoformat()
                    
                    await ctx.checkpointer.aput(
                        config,
                        snapshot.checkpoint,
                        {"status": "paused"},
                        {}
                    )
                    
                    await websocket.send_json({
                        "type": "task_paused",
                        "thread_id": thread_id,
                        "state": state,
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
            elif action == "resume_task":
                thread_id = data.get("thread_id")
                if not thread_id:
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id is required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                
                try:
                    modifications = data.get("modifications")
                    state = await get_paused_task_state(thread_id)
                    if not state:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"No paused task found for {thread_id}",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                    
                    if modifications:
                        state.update(modifications)
                        if "plan" in modifications:
                            state["plan"] = modifications["plan"]
                            state["current_step"] = 0
                    
                    async for event in resume_task_from_checkpoint(thread_id, modifications):
                        await websocket.send_json(event)
                        
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
            elif action == "modify_step":
                thread_id = data.get("thread_id")
                step_index = data.get("step_index")
                new_step = data.get("new_step")
                
                if not all([thread_id, step_index is not None, new_step]):
                    await websocket.send_json({
                        "type": "error",
                        "message": "thread_id, step_index, and new_step are required",
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    continue
                
                try:
                    ctx = synthai
                    config = {"configurable": {"thread_id": thread_id}}
                    snapshot = await ctx.checkpointer.aget_tuple(config)
                    
                    if not snapshot:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Task {thread_id} not found",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                        continue
                    
                    state = snapshot.checkpoint.get("channel_values", {})
                    plan = state.get("plan", [])
                    
                    if isinstance(plan, list) and 0 <= step_index < len(plan):
                        plan[step_index] = new_step
                        state["plan"] = plan
                        
                        await ctx.checkpointer.aput(
                            config,
                            snapshot.checkpoint,
                            {"plan": plan},
                            {}
                        )
                        
                        await websocket.send_json({
                            "type": "step_modified",
                            "thread_id": thread_id,
                            "result": {"step_index": step_index, "new_step": new_step},
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                    else:
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Invalid step_index {step_index}",
                            "timestamp": datetime.now(timezone.utc).isoformat()
                        })
                except Exception as e:
                    await websocket.send_json({
                        "type": "error",
                        "message": str(e),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    })
                    
            elif action == "ping":
                await websocket.send_json({"type": "pong", "timestamp": datetime.now(timezone.utc).isoformat()})
                
    except WebSocketDisconnect:
        logger.info("websocket.disconnected", client_id=client_id)
    except Exception as exc:
        code, user_message_error = to_user_error(exc)
        logger.exception("websocket.error", client_id=client_id, error_code=code, error=str(exc))
        await websocket.send_json({
            "type": "error",
            "error_code": code,
            "message": user_message_error,
            "error": str(exc),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })