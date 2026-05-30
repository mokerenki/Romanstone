from app.core.model_router import ModelRouter

class VerifierNode:
    def __init__(self, router: ModelRouter):
        self.router = router

    async def __call__(self, state: dict) -> dict:
        task = state["task"]
        results = state.get("results", [])
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
        resp = await self.router.route("verification", [{"role": "user", "content": prompt}])
        answer_text = resp.content.strip().lower()
        if "yes" in answer_text and "no" not in answer_text:
            state["done"] = True
            state["final_answer"] = last_output
        else:
            state["done"] = False
            state["feedback"] = resp.content
        return state