"""
Task persistence utilities - shared between tasks.py and websocket_handler.py
Breaks the circular import between tasks.py and websocket_handler.py.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

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