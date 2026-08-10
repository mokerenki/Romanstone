# backend/app/api/history_api.py

from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List
import structlog
from datetime import datetime

from app.core.history_store import HistoryStore

logger = structlog.get_logger("synthai.api.history")
router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("/tasks")
async def list_tasks(
    user_id: str = Query("dashboard", description="User ID"),
    limit: int = Query(50, ge=1, le=200),
    status: Optional[str] = Query(None, description="Filter by status"),
    from_date: Optional[str] = Query(None, description="ISO date string"),
    to_date: Optional[str] = Query(None, description="ISO date string"),
):
    """List tasks with filtering."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        tasks = await history_store.list_user_tasks(
            user_id=user_id,
            limit=limit,
            status=status,
            from_date=from_date,
            to_date=to_date
        )
        
        return {
            "tasks": tasks,
            "total": len(tasks),
            "limit": limit,
        }
    except Exception as e:
        logger.exception("history.list_tasks_failed", error=str(e))
        raise HTTPException(500, f"Failed to list tasks: {str(e)}")


@router.get("/tasks/{thread_id}")
async def get_task_detail(thread_id: str):
    """Get full task detail including timeline."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        task = await history_store.get_full_task(thread_id)
        if not task:
            raise HTTPException(404, f"Task {thread_id} not found")
        
        return task
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("history.get_task_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(500, f"Failed to get task: {str(e)}")


@router.get("/tasks/{thread_id}/timeline")
async def get_task_timeline(
    thread_id: str,
    start_index: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
):
    """Get paginated timeline events."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        timeline = await history_store.get_task_timeline(thread_id)
        
        total = len(timeline)
        events = timeline[start_index:start_index + limit]
        
        return {
            "thread_id": thread_id,
            "events": events,
            "total": total,
            "start_index": start_index,
            "limit": limit,
            "has_more": start_index + limit < total,
        }
    except Exception as e:
        logger.exception("history.get_timeline_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(500, f"Failed to get timeline: {str(e)}")


@router.get("/tasks/{thread_id}/export")
async def export_task(thread_id: str, format: str = "json"):
    """Export task history in various formats."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        task = await history_store.get_full_task(thread_id)
        if not task:
            raise HTTPException(404, f"Task {thread_id} not found")
        
        if format == "json":
            return task
        elif format == "markdown":
            return await _export_markdown(task)
        else:
            raise HTTPException(400, f"Unsupported format: {format}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("history.export_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(500, f"Failed to export task: {str(e)}")


async def _export_markdown(task: dict) -> dict:
    """Convert task history to markdown."""
    lines = []
    lines.append(f"# Task: {task.get('task', 'Untitled')}")
    lines.append("")
    lines.append(f"- **Thread ID:** {task.get('thread_id')}")
    lines.append(f"- **Status:** {task.get('status')}")
    lines.append(f"- **Created:** {task.get('created_at')}")
    lines.append(f"- **Completed:** {task.get('completed_at', 'N/A')}")
    lines.append(f"- **Duration:** {task.get('duration_seconds', 0):.1f}s")
    lines.append(f"- **Cost:** ${task.get('total_cost_usd', 0):.6f}")
    lines.append(f"- **Tool Calls:** {task.get('tool_calls_count', 0)}")
    lines.append("")
    
    if task.get("summary"):
        lines.append("## Summary")
        lines.append("")
        lines.append(task["summary"])
        lines.append("")
    
    lines.append("## Timeline")
    lines.append("")
    
    timeline = task.get("timeline", [])
    for i, event in enumerate(timeline):
        event_type = event.get("type", "unknown")
        timestamp = event.get("timestamp", "")
        data = event.get("data", {})
        
        lines.append(f"### {i + 1}. {event_type.replace('_', ' ').title()}")
        lines.append(f"- **Time:** {timestamp}")
        
        if "step" in data:
            lines.append(f"- **Step:** {data['step']}")
        if "tool" in data:
            lines.append(f"- **Tool:** {data['tool']}")
        if "output" in data:
            lines.append(f"- **Output:** {data['output'][:200]}...")
        if "status" in data:
            lines.append(f"- **Status:** {data['status']}")
        if "error" in data:
            lines.append(f"- **Error:** {data['error']}")
        
        lines.append("")
    
    return {
        "format": "markdown",
        "content": "\n".join(lines),
        "filename": f"task_{task.get('thread_id')}.md"
    }


@router.delete("/tasks/{thread_id}")
async def delete_task(thread_id: str):
    """Delete a task history."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        deleted = await history_store.delete_task(thread_id)
        if not deleted:
            raise HTTPException(404, f"Task {thread_id} not found")
        
        return {"status": "deleted", "thread_id": thread_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("history.delete_failed", thread_id=thread_id, error=str(e))
        raise HTTPException(500, f"Failed to delete task: {str(e)}")


@router.get("/stats")
async def get_stats(user_id: str = Query("dashboard")):
    """Get task statistics."""
    try:
        history_store = HistoryStore()
        await history_store.ensure_initialized()
        
        stats = await history_store.get_task_stats(user_id)
        return stats
    except Exception as e:
        logger.exception("history.stats_failed", error=str(e))
        raise HTTPException(500, f"Failed to get stats: {str(e)}")