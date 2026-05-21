"""PlannerNode — Phase 0 (COMPLETE)

Generates execution plans using Kimi K2.
"""

import json
from typing import Any, Dict, List

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from opik import track

from app.core.config import CONFIG
from app.core.model_router import ModelResponse, ModelRouter

logger = structlog.get_logger("aether.planner")

PLANNER_SYSTEM_PROMPT = """You are the Planner node of Aether.
Break down user tasks into deterministic tool calls.

Available tools:
{tool_descriptions}

Rules:
1. Output ONLY valid JSON matching the schema.
2. Each step needs unique step_id, description, optional tool_name, tool_args, depends_on.
3. If no tool needed, set tool_name to null.

Respond with:
{{"plan": [{{"step_id": "step_1", "description": "...", "tool_name": "...", "tool_args": {{...}}, "depends_on": []}}], "reasoning": "..."}}
"""


class PlannerNode:
    def __init__(self, router: ModelRouter, registry):
        self.router = router
        self.registry = registry

    @track(project_name="aether", name="planner_node")
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("planner.start", task_id=state.get("task_id"))

        tool_descriptions = self.registry.describe_all()
        system_prompt = PLANNER_SYSTEM_PROMPT.format(
            tool_descriptions=json.dumps(tool_descriptions, indent=2)
        )

        user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
        if not user_messages:
            return {"status": "failed", "final_answer": "No user message found."}

        latest = user_messages[-1].content
        messages = [{"role": "user", "content": latest}]

        if state.get("scratchpad"):
            messages.insert(0, {"role": "user", "content": f"Previous feedback: {state['scratchpad']}"})

        try:
            response: ModelResponse = await self.router.route(
                role=ModelRouter.ROLE_PLANNING,
                messages=messages,
                system_prompt=system_prompt,
                temperature=0.3,
                max_tokens=4096,
            )

            content = response.content.strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            content = content.strip()

            plan_data = json.loads(content)
            raw_plan = plan_data.get("plan", [])

            plan = []
            for idx, step in enumerate(raw_plan):
                plan.append({
                    "step_id": step.get("step_id", f"step_{idx}"),
                    "description": step.get("description", ""),
                    "tool_name": step.get("tool_name"),
                    "tool_args": step.get("tool_args", {}),
                    "status": "pending",
                    "result": None,
                    "depends_on": step.get("depends_on", []),
                })

            metrics = state.get("cost_metrics", {
                "kimi_input_tokens": 0, "kimi_output_tokens": 0,
                "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
                "total_cost_usd": 0.0, "tool_calls": 0
            })
            metrics["kimi_input_tokens"] += response.usage.input_tokens
            metrics["kimi_output_tokens"] += response.usage.output_tokens
            metrics["total_cost_usd"] += response.usage.total_cost(
                CONFIG.kimi_k2.input_cost_per_1m, CONFIG.kimi_k2.output_cost_per_1m
            )

            logger.info("planner.complete", steps=len(plan))

            return {
                "plan": plan,
                "current_step_index": 0,
                "status": "executing",
                "planning_iterations": state.get("planning_iterations", 0) + 1,
                "cost_metrics": metrics,
                "messages": [AIMessage(content=f"Plan: {json.dumps(plan_data, indent=2)}")],
            }

        except json.JSONDecodeError as e:
            logger.error("planner.json_error", error=str(e))
            return {"status": "failed", "final_answer": f"Failed to parse plan: {str(e)}"}
        except Exception as e:
            logger.error("planner.error", error=str(e))
            return {"status": "failed", "final_answer": f"Planning failed: {str(e)}"}
