from langchain_core.messages import HumanMessage
from app.tools.registry import ToolRegistry
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter

class ExecutorNode:
    def __init__(self, registry: ToolRegistry, router: KimiDeepSeekRouter):
        self.registry = registry
        self.router = router

    async def __call__(self, state: dict) -> dict:
        plan = state.get("plan", [])
        current_step = state.get("current_step", 0)
        results = state.get("results", [])

        if not plan or current_step >= len(plan):
            new_state = {**state}
            new_state["results"] = results
            new_state["current_step"] = current_step
            new_state["status"] = "completed"
            new_state["done"] = True
            return new_state

        step = plan[current_step]

        if step.get("tool_name"):
            tool = self.registry.get(step["tool_name"])
            if tool:
                result = await tool.execute(**step.get("tool_args", {}))
                results.append({
                    "step": step.get("description", ""),
                    "tool": step["tool_name"],
                    "output": result.get("output", "") if isinstance(result, dict) else str(result)
                })
            else:
                results.append({
                    "step": step.get("description", ""),
                    "tool": step["tool_name"],
                    "output": f"Tool not found: {step['tool_name']}"
                })
        else:
            context_parts = []
            for r in results:
                if isinstance(r, dict):
                    context_parts.append(f"Step: {r.get('step', '')}\nResult: {r.get('output', '')}")
                else:
                    context_parts.append(str(r))
            context = "\n\n".join(context_parts)

            description = step.get("description", "Complete the task")
            prompt = f"""Based on the information gathered, complete the following action.

Action: {description}

Context from previous steps:
{context}

User's original task: {state['task']}

If this is a final answer, write a clear, complete, and concise paragraph that directly answers the user. Do not include raw JSON or tool outputs. Use proper grammar."""
            llm_resp = await self.router.route(
                "general_chat",
                [HumanMessage(content=prompt)]
            )
            results.append({
                "step": description,
                "output": llm_resp.content
            })

        new_state = {**state}
        new_state["results"] = results
        new_state["current_step"] = current_step + 1
        new_state["planning_iterations"] = state.get("planning_iterations", 0) + 1
        return new_state