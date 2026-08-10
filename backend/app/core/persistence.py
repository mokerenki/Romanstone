# backend/app/core/persistence.py

"""
Task persistence utilities - shared between tasks.py and websocket_handler.py
Breaks the circular import between tasks.py and websocket_handler.py.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List  # <-- FIXED: Added List

from app.core.context import synthai

TASK_PROGRESS_PREFIX = "synthai:task:progress"
TASK_STATUS_PREFIX = "synthai:task:status"
TASK_TTL_SECONDS = 86400  # 24 hours


def _get_context():
    """Get the SynthAI context. Raises clear error if not initialized."""
    synthai.ensure_initialized()
    return synthai


async def persist_task_progress(thread_id: str, state: Dict[str, Any]) -> None:
    """Persist incremental task progress to Redis."""
    ctx = _get_context()
    key = f"{TASK_PROGRESS_PREFIX}:{thread_id}"
    payload = {
        "thread_id": thread_id,
        "task": state.get("task", ""),
        "status": state.get("status", "pending"),
        "current_step": state.get("current_step", 0),
        "plan": json.dumps(state.get("plan", [])),
        "results": json.dumps(state.get("results", [])),
        "final_answer": state.get("final_answer") or "",
        "cost_metrics": json.dumps(state.get("cost_metrics", {})),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await ctx.redis_client.hset(key, mapping=payload)
    await ctx.redis_client.expire(key, TASK_TTL_SECONDS)


async def get_task_progress(thread_id: str) -> Optional[Dict[str, Any]]:
    """Get task progress from Redis."""
    ctx = _get_context()
    key = f"{TASK_PROGRESS_PREFIX}:{thread_id}"
    data = await ctx.redis_client.hgetall(key)
    if not data:
        return None
    result = {
        k.decode() if isinstance(k, bytes) else k: 
        v.decode() if isinstance(v, bytes) else v 
        for k, v in data.items()
    }
    for field in ("plan", "results", "cost_metrics"):
        val = result.get(field)
        if val:
            try:
                result[field] = json.loads(val)
            except Exception:
                pass
    return result


async def get_task_metadata(task_id: str) -> Optional[Dict[str, Any]]:
    """Fetch task metadata from Redis."""
    ctx = _get_context()
    key = f"{TASK_STATUS_PREFIX}:{task_id}"
    data = await ctx.redis_client.hgetall(key)
    if not data:
        return None
    return {
        k.decode() if isinstance(k, bytes) else k: 
        v.decode() if isinstance(v, bytes) else v 
        for k, v in data.items()
    }


async def set_task_metadata(task_id: str, metadata: Dict[str, Any]) -> None:
    """Store task metadata in Redis."""
    ctx = _get_context()
    key = f"{TASK_STATUS_PREFIX}:{task_id}"
    encoded = {
        k: str(v) if not isinstance(v, str) else v 
        for k, v in metadata.items()
    }
    await ctx.redis_client.hset(key, mapping=encoded)
    await ctx.redis_client.expire(key, TASK_TTL_SECONDS)


# ─── Phase 0: Task History ─────────────────────────────────────


async def store_checkpoint_snapshot(thread_id: str, checkpoint: dict) -> None:
    """
    Store full checkpoint state for history replay.
    Called from the executor after each node execution.
    """
    ctx = _get_context()
    key = f"synthai:checkpoint:history:{thread_id}"
    
    # Get existing history or create new
    existing = await ctx.redis_client.get(key)
    history = json.loads(existing) if existing else {"thread_id": thread_id, "snapshots": []}
    
    # Add new snapshot with timestamp
    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "state": {
            "plan": checkpoint.get("plan", []),
            "current_step": checkpoint.get("current_step", 0),
            "results": checkpoint.get("results", []),
            "status": checkpoint.get("status", "pending"),
            "final_answer": checkpoint.get("final_answer"),
            "cost_metrics": checkpoint.get("cost_metrics", {}),
            "verification": checkpoint.get("verification"),
        }
    }
    
    history["snapshots"].append(snapshot)
    
    # Keep only last 100 snapshots to prevent memory issues
    if len(history["snapshots"]) > 100:
        history["snapshots"] = history["snapshots"][-100:]
    
    await ctx.redis_client.setex(key, 86400 * 30, json.dumps(history))  # 30 days TTL


async def get_task_history(thread_id: str) -> Optional[dict]:
    """Retrieve full task history for a thread."""
    ctx = _get_context()
    key = f"synthai:checkpoint:history:{thread_id}"
    data = await ctx.redis_client.get(key)
    if data:
        return json.loads(data)
    return None


async def list_user_tasks(user_id: str, limit: int = 50) -> List[dict]:
    """List all tasks for a user with metadata."""
    ctx = _get_context()
    pattern = f"synthai:task:status:*"
    keys = await ctx.redis_client.keys(pattern)
    
    tasks = []
    for key in keys:
        key_str = key.decode() if isinstance(key, bytes) else key
        task_id = key_str.split(":")[-1]
        metadata = await get_task_metadata(task_id)
        if metadata and metadata.get("user_id") == user_id:
            tasks.append({
                "task_id": task_id,
                "thread_id": metadata.get("thread_id"),
                "task": metadata.get("task"),
                "status": metadata.get("status"),
                "created_at": metadata.get("created_at"),
                "completed_at": metadata.get("completed_at"),
                "cost_metrics": json.loads(metadata.get("cost_metrics", "{}")),
                "final_answer": metadata.get("final_answer"),
            })
    
    tasks.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return tasks[:limit]