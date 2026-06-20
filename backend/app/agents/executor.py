from langchain_core.messages import HumanMessage
from app.tools.registry import ToolRegistry
from app.core.model_router import ModelRouter

class ExecutorNode:
    def __init__(self, registry: ToolRegistry, router: ModelRouter):
        self.registry = registry
        self.router = router

    async def __call__(self, state: dict) -> dict:
        step = state["plan"][state["current_step"]]
        results = state.get("results", [])

        if step.get("tool"):
            tool = self.registry.get(step["tool"])
            result = await tool.execute(**step.get("args", {}))
            results.append({
                "step": step.get("description", ""),
                "tool": step["tool"],
                "output": result.get("output", "")
            })
        else:
            # No tool – use LLM with all previous results as context
            # Build a clean context string
            context_parts = []
            for r in results:
                if isinstance(r, dict):
                    context_parts.append(f"Step: {r.get('step', '')}\nResult: {r.get('output', '')}")
                else:
                    context_parts.append(str(r))
            context = "\n\n".join(context_parts)

            prompt = f"""Based on the information gathered, complete the following action.

Action: {step['action']}

Context from previous steps:
{context}

User's original task: {state['task']}

If this is a final answer, write a clear, complete, and concise paragraph that directly answers the user. Do not include raw JSON or tool outputs. Use proper grammar."""
            llm_resp = await self.router.route(
                self.router.ROLE_VERIFICATION,
                [HumanMessage(content=prompt)]
            )
            results.append({
                "step": step.get("description", ""),
                "output": llm_resp.content
            })

        new_state = {**state}
        new_state["results"] = results
        new_state["current_step"] = state["current_step"] + 1
        return new_state