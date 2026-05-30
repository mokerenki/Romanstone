import json
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry

class PlannerNode:
    def __init__(self, router: ModelRouter, registry: ToolRegistry):
        self.router = router
        self.registry = registry

    async def __call__(self, state: dict) -> dict:
        task = state["task"]
        tools = self.registry.describe_all()
        feedback = state.get("feedback", "")

        prompt = f"""You are a planning agent. Break down the user's task into steps.
Available tools:
{json.dumps(tools, indent=2)}

CRITICAL RULES:
- For factual questions: first use the 'browser' tool to retrieve raw information.
- After you have collected all necessary information, your VERY LAST step MUST be:
  {{"action": "formulate_final_answer", "tool": "", "args": {{}}, "description": "Write the final answer to the user in a complete, self-contained paragraph"}}
- When you write the final answer, DO NOT return raw tool output. Summarise the information into a clear, grammatically correct, and direct answer that fully satisfies the user.
- If the task is a calculation, you can use 'python_repl' directly, then formulate the answer.
- If there is previous feedback: {feedback}, adjust your plan accordingly.

Task: {task}

Return ONLY a JSON list of steps in the exact format:
[
  {{"action": "...", "tool": "...", "args": {{...}}, "description": "..."}},
  ...
]
The last step MUST be the final answer step."""
        resp = await self.router.route("planning", [{"role": "user", "content": prompt}])
        try:
            plan = json.loads(resp.content)
            if not isinstance(plan, list):
                plan = [{"action": task}]
        except Exception:
            plan = [{"action": task}]
        return {**state, "plan": plan, "current_step": 0}