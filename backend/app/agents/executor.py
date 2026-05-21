"""ExecutorNode — Phase 0 (COMPLETE)

Executes plan steps using the ToolRegistry.
"""

import asyncio
import json
import time
from typing import Any, Dict, List

import structlog
from langchain_core.messages import ToolMessage
from opik import track

logger = structlog.get_logger("aether.executor")


class ExecutorNode:
    def __init__(self, registry):
        self.registry = registry

    @track(project_name="aether", name="executor_node")
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("executor.start", task_id=state.get("task_id"))

        plan = state.get("plan", [])
        current_idx = state.get("current_step_index", 0)
        tool_calls = state.get("tool_calls", [])
        metrics = state.get("cost_metrics", {
            "kimi_input_tokens": 0, "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0, "tool_calls": 0
        })

        if current_idx >= len(plan):
            return {"status": "verifying"}

        step = plan[current_idx]

        for dep_id in step.get("depends_on", []):
            dep = next((s for s in plan if s["step_id"] == dep_id), None)
            if not dep or dep["status"] != "completed":
                return {"status": "failed", "final_answer": f"Dependency {dep_id} not met"}

        step["status"] = "running"
        tool_name = step.get("tool_name")
        tool_args = step.get("tool_args", {})

        if not tool_name:
            step["status"] = "completed"
            step["result"] = step.get("description", "")
            return {
                "plan": plan,
                "current_step_index": current_idx + 1,
                "status": "verifying" if (current_idx + 1) >= len(plan) else "executing",
            }

        start = time.perf_counter()
        result_str = None
        error_str = None
        retries = 0
        max_retries = 3

        while retries <= max_retries:
            try:
                tool = self.registry.get(tool_name)
                if not tool:
                    raise ValueError(f"Tool '{tool_name}' not found")
                result = await tool.execute(**tool_args)
                result_str = json.dumps(result) if not isinstance(result, str) else result
                break
            except Exception as e:
                retries += 1
                error_str = str(e)
                if retries > max_retries:
                    break
                await asyncio.sleep(0.5 * retries)

        latency = (time.perf_counter() - start) * 1000

        tool_call = {
            "tool_name": tool_name,
            "arguments": tool_args,
            "result": result_str,
            "error": error_str,
            "retry_count": retries,
            "latency_ms": latency,
        }
        tool_calls.append(tool_call)
        metrics["tool_calls"] = len(tool_calls)

        if error_str and retries > max_retries:
            step["status"] = "failed"
            step["result"] = error_str
            return {
                "plan": plan, "tool_calls": tool_calls, "cost_metrics": metrics,
                "status": "failed",
                "final_answer": f"Tool '{tool_name}' failed after {max_retries} retries: {error_str}",
            }

        step["status"] = "completed"
        step["result"] = result_str
        next_idx = current_idx + 1
        is_done = next_idx >= len(plan)

        return {
            "plan": plan,
            "current_step_index": next_idx,
            "tool_calls": tool_calls,
            "cost_metrics": metrics,
            "status": "verifying" if is_done else "executing",
            "messages": [ToolMessage(content=result_str or error_str or "", tool_call_id=step["step_id"])],
        }
