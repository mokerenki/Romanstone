from langchain_core.messages import HumanMessage  # type: ignore[import-not-found]
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
        tool_name = step.get("tool_name")

        if tool_name:
            tool = self.registry.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(**step.get("tool_args", {}))
                    output = result.get("output", "") if isinstance(result, dict) else str(result)
                except Exception as e:
                    output = f"Error executing tool '{tool_name}': {e}"
            else:
                output = f"Error: Tool '{tool_name}' not found."
            results.append({
                "step": step.get("description", ""),
                "tool": tool_name,
                "output": output
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
            try:
                llm_resp = await self.router.route("fallback", [HumanMessage(content=prompt)])
                output = llm_resp.content
            except Exception as e:
                output = f"Error synthesizing step: {e}"
            results.append({
                "step": description,
                "output": output
            })

        new_current_step = current_step + 1
        new_state = {**state}
        new_state["results"] = results
        new_state["current_step"] = new_current_step
        new_state["planning_iterations"] = state.get("planning_iterations", 0) + 1

        # If that was the last step in the plan, synthesize the final answer now
        # from everything gathered, so the Verifier can do a proper final-answer
        # check and the graph can correctly recognize the task is complete.
        if new_current_step >= len(plan) and not state.get("final_answer"):
            context_parts = []
            for r in results:
                if isinstance(r, dict):
                    context_parts.append(f"Step: {r.get('step', '')}\nResult: {r.get('output', '')}")
                else:
                    context_parts.append(str(r))
            context = "\n\n".join(context_parts)
            final_prompt = f"""Based on all the information gathered below, write a clear, complete,
and concise final answer to the user's original question. Do not include raw JSON,
tool names, or step numbers -- just a direct, well-written answer.

User's original task: {state['task']}

Gathered information:
{context}
"""
            try:
                final_resp = await self.router.route("fallback", [HumanMessage(content=final_prompt)])
                new_state["final_answer"] = final_resp.content
            except Exception as e:
                new_state["final_answer"] = (
                    results[-1]["output"] if results else f"Could not synthesize a final answer: {e}"
                )

        return new_state