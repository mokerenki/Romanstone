from langchain_core.messages import HumanMessage
from app.core.model_router import ModelRouter
from langchain_core.load import dumps
from app.state import TaskState


class VerifierNode:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def __call__(self, state: TaskState) -> TaskState:
        task = state["task"]
        results = state.get("results", [])

        # Extract the last step's output as the candidate final answer
        last_output = ""
        if results:
            last = results[-1]
            if isinstance(last, dict):
                last_output = last.get("output", "")
            else:
                last_output = str(last)

        prompt = f"""Task: {task}
Final answer to verify: "{last_output}"

Is this answer complete, self-contained, grammatically correct, and directly responsive to the user?
Answer only 'yes' or 'no'. If 'no', briefly explain what is missing."""

        resp = await self.router.route("verification", [HumanMessage(content=prompt)])
        answer_text = resp.content.strip().lower()

        if "yes" in answer_text and "no" not in answer_text:
            # Return a new state dict — never mutate state in-place
            return {
                **state,
                "done": True,
                "final_answer": last_output,
                "verification": resp.content,
                "needs_replan": False,
            }
        else:
            return {
                **state,
                "done": False,
                "feedback": resp.content,
                "verification": resp.content,
                "needs_replan": True,
            }
