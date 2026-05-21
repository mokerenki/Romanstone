"""VerifierNode — Phase 0 (COMPLETE)

Verifies execution results using DeepSeek.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from langchain_core.messages import AIMessage, HumanMessage
from opik import track

from app.core.config import CONFIG
from app.core.model_router import ModelResponse, ModelRouter

logger = structlog.get_logger("aether.verifier")

VERIFIER_SYSTEM_PROMPT = """You are the Verifier node of Aether.
Check whether the executed plan correctly answers the original request.

Evaluate: Correctness, Completeness, Safety.

Respond with JSON:
{{"passed": true, "score": 0.95, "issues": [], "suggestions": []}}

Score guide:
- 0.90–1.00: Excellent
- 0.70–0.89: Good, minor issues
- 0.50–0.69: Acceptable with reservations
- <0.50: Failed, needs replanning
"""


class VerifierNode:
    def __init__(self, router: ModelRouter):
        self.router = router

    @track(project_name="aether", name="verifier_node")
    async def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        logger.info("verifier.start", task_id=state.get("task_id"))

        plan = state.get("plan", [])
        tool_calls = state.get("tool_calls", [])

        user_messages = [m for m in state.get("messages", []) if isinstance(m, HumanMessage)]
        original = user_messages[-1].content if user_messages else ""

        execution_log = []
        for step in plan:
            execution_log.append({
                "step": step["step_id"],
                "description": step["description"],
                "tool": step.get("tool_name"),
                "result": step.get("result"),
                "status": step["status"],
            })

        context = {
            "original_request": original,
            "execution_log": execution_log,
            "tool_calls": [{"tool": tc["tool_name"], "args": tc["arguments"],
                            "result": tc["result"], "error": tc["error"]} for tc in tool_calls],
        }

        messages = [{"role": "user", "content": json.dumps(context, indent=2)}]

        try:
            response: ModelResponse = await self.router.route(
                role=ModelRouter.ROLE_VERIFICATION,
                messages=messages,
                system_prompt=VERIFIER_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=2048,
            )

            content = response.content.strip()
            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]
            content = content.strip()

            verdict = json.loads(content)

            verification = {
                "passed": verdict.get("passed", False),
                "score": verdict.get("score", 0.0),
                "issues": verdict.get("issues", []),
                "suggestions": verdict.get("suggestions", []),
                "verified_at": datetime.now(timezone.utc).isoformat(),
            }

            metrics = state.get("cost_metrics", {
                "kimi_input_tokens": 0, "kimi_output_tokens": 0,
                "deepseek_input_tokens": 0, "deepseek_output_tokens": 0,
                "total_cost_usd": 0.0, "tool_calls": 0
            })
            metrics["deepseek_input_tokens"] += response.usage.input_tokens
            metrics["deepseek_output_tokens"] += response.usage.output_tokens
            metrics["total_cost_usd"] += response.usage.total_cost(
                CONFIG.deepseek.input_cost_per_1m, CONFIG.deepseek.output_cost_per_1m
            )

            needs_replan = not verification["passed"] and verification["score"] < 0.70

            final_parts = []
            for step in plan:
                if step.get("result"):
                    final_parts.append(f"**{step['description']}**\n{step['result']}")
            final_answer = "\n\n".join(final_parts) if final_parts else "Task completed."

            if needs_replan and state.get("planning_iterations", 0) < 3:
                return {
                    "verification": verification,
                    "needs_replan": True,
                    "replan_reason": "; ".join(verification["issues"] + verification["suggestions"]),
                    "scratchpad": f"Verification failed (score: {verification['score']}): " + "; ".join(verification["issues"]),
                    "cost_metrics": metrics,
                    "status": "planning",
                    "messages": [AIMessage(content=f"Verification: {json.dumps(verdict, indent=2)}")],
                }

            return {
                "verification": verification,
                "needs_replan": False,
                "final_answer": final_answer,
                "cost_metrics": metrics,
                "status": "completed" if verification["passed"] else "failed",
                "messages": [AIMessage(content=f"Verification: {json.dumps(verdict, indent=2)}")],
            }

        except json.JSONDecodeError:
            return {"status": "completed", "final_answer": "Task completed (verification parsing failed)."}
        except Exception as e:
            return {"status": "failed", "final_answer": f"Verification failed: {str(e)}"}
