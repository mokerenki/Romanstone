import structlog
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage  # type: ignore[import-not-found]
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.core.llm_json import parse_llm_json

logger = structlog.get_logger("aether.agents.verifier")

class Verifier:
    """
    The Verifier node evaluates the output of the Planner and Executor.
    It provides structured feedback to enable self-correction and ensures
    the agent's actions align with the overall goal.
    """

    def __init__(self, model_router: KimiDeepSeekRouter):
        self.model_router = model_router
        logger.info("verifier.initialized")

    def _trigger_replan(self, state: dict, feedback: str) -> None:
        """
        Single place that puts the graph into "replan" mode.

        ─── BUGFIX ───────────────────────────────────────────────────
        Every call site that flips needs_replan=True must also clear
        final_answer. Previously a failed *final answer* verification
        set needs_replan=True but left the old (failed) final_answer
        sitting in state. ExecutorNode only regenerates a final answer
        when `not state.get("final_answer")`, so after replanning the
        executor would run the new plan's steps but skip synthesis
        entirely -- the verifier then re-checked the exact same stale,
        already-failed answer against the new context, failed it again
        for the same reason, and replan_count ticked up without the
        answer ever having a chance to change. That's what was burning
        through max_replans while never actually producing (or fixing)
        an answer, and why the agent seemed to give up on "no context"
        so fast.
        """
        state["needs_replan"] = True
        state["done"] = False
        state["final_answer"] = None
        state["replan_feedback"] = feedback
        state["feedback"] = feedback

    async def __call__(self, state: dict) -> dict:
        """
        LangGraph node entry point. Called when the graph reaches the "verifier" node.
        It inspects the state, runs the appropriate verification, and returns an updated state.
        """
        logger.info("verifier.called", state_keys=list(state.keys()))

        # Determine what to verify
        plan = state.get("plan")
        final_answer = state.get("final_answer")
        overall_goal = state.get("task", "")
        context = self._build_context(state)

        if final_answer:
            any_tools_used = any(
                isinstance(r, dict) and r.get("tool")
                for r in state.get("results", [])
            )
            if not any_tools_used:
                state["verification"] = {
                    "status": "PASS",
                    "score": 95,
                    "feedback": "Direct answer — no tools used, no verification needed.",
                }
                state["done"] = True
                state["status"] = "completed"
                return state

        # If we have a final answer, verify it
        if final_answer:
            verification = await self.verify_final_answer(overall_goal, final_answer, context)
            state["verification"] = verification
            # If the final answer passes, mark as done
            if verification.get("status") == "PASS":
                state["done"] = True
                state["status"] = "completed"
            else:
                # Otherwise, replan -- and make sure the stale answer
                # doesn't survive to block the next synthesis attempt.
                self._trigger_replan(
                    state,
                    verification.get("feedback", "Final answer verification failed."),
                )
            return state

        # If we have a plan but haven't executed it yet, verify the plan
        if plan and state.get("current_step", 0) == 0:
            verification = await self.verify_plan(plan, overall_goal)
            state["verification"] = verification
            if verification.get("status") != "PASS":
                self._trigger_replan(
                    state,
                    verification.get("feedback", "Plan verification failed."),
                )
            return state

        # If we're in the middle of execution, verify the last step's output
        results = state.get("results", [])
        if results and plan:
            last_step_index = len(results) - 1
            if last_step_index < len(plan):
                step = plan[last_step_index]
                step_output = results[-1].get("output", "")
                expected_outcome = step.get("expected_outcome", "No expected outcome provided.")
                verification = await self.verify_step_output(step, step_output, expected_outcome)
                state["verification"] = verification
                if verification.get("status") != "PASS":
                    self._trigger_replan(
                        state,
                        verification.get("feedback", "Step verification failed."),
                    )
            else:
                # All steps have been executed? But no final answer yet – maybe the plan is done.
                # Let's check if we've executed all steps.
                if state.get("current_step", 0) >= len(plan):
                    # All steps done, but no final answer? The executor should have produced one.
                    # For safety, set done to True and let the graph end.
                    state["done"] = True
                    state["status"] = "completed"
                    if not state.get("final_answer"):
                        state["final_answer"] = "Task completed, but no final answer was generated."
        else:
            # No plan or results? Maybe the graph just started; we can skip verification.
            logger.warning("verifier.no_plan_or_results", state=state)

        return state

    def _build_context(self, state: dict) -> str:
        """Build a context string from the state for verification prompts."""
        parts = []
        if state.get("task"):
            parts.append(f"Overall Goal: {state['task']}")
        if state.get("results"):
            parts.append("Previous Results:")
            for r in state["results"]:
                if isinstance(r, dict):
                    parts.append(f"  - {r.get('step', '')}: {r.get('output', '')}")
                else:
                    parts.append(f"  - {r}")
        return "\n".join(parts)

    # ----- Existing helper methods (unchanged) -----

    async def verify_plan(self, plan: List[Dict[str, Any]], overall_goal: str) -> Dict[str, Any]:
        """Verifies the generated plan against the overall goal."""
        system_message = SystemMessage(content=(
            "You are an expert AI Verifier. Your task is to critically evaluate a given plan "
            "against an overall goal. Provide constructive feedback to help the Planner improve."
            "Focus on clarity, completeness, logical flow, and alignment with the goal."
            "Respond with a JSON object containing 'status' (PASS/FAIL), 'score' (0-100), "
            "and 'feedback' (detailed suggestions for improvement)."
            "If the plan is good, explain why. If it's bad, explain what's missing or wrong."
        ))
        user_message = HumanMessage(content=f"""
        Overall Goal: {overall_goal}

        Plan to Verify:
        {json.dumps(plan, indent=2)}

        Please provide your verification status, score, and detailed feedback.
        """)
        messages = [system_message, user_message]
        try:
            response = await self.model_router.route("verification", messages)
            feedback = parse_llm_json(response.content)
            logger.info("verifier.plan_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.plan_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify plan: {str(e)}"}

    async def verify_step_output(self, step: Dict[str, Any], step_output: Any, expected_outcome: str) -> Dict[str, Any]:
        """Verifies the output of a single step against its expected outcome."""
        system_message = SystemMessage(content=(
            "You are an expert AI Verifier. Your task is to evaluate if a step's output "
            "achieved its expected outcome. Provide constructive feedback if it failed."
            "Respond with a JSON object containing 'status' (PASS/FAIL), 'score' (0-100), "
            "and 'feedback' (detailed suggestions for improvement or confirmation of success)."
        ))
        user_message = HumanMessage(content=f"""
        Step: {json.dumps(step, indent=2)}

        Expected Outcome: {expected_outcome}

        Actual Step Output:
        {str(step_output)}

        Did the step achieve its expected outcome? Provide status, score, and feedback.
        """)
        messages = [system_message, user_message]
        try:
            response = await self.model_router.route("verification", messages)
            feedback = parse_llm_json(response.content)
            logger.info("verifier.step_output_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.step_output_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify step output: {str(e)}"}

    async def verify_final_answer(self, overall_goal: str, final_answer: str, context: str) -> Dict[str, Any]:
        """Verifies the final answer against the overall goal and provided context."""
        system_message = SystemMessage(content=(
            "You are an expert AI Verifier. Your task is to critically evaluate a final answer "
            "against the overall goal and provided context. Ensure the answer is complete, "
            "accurate, clear, and directly addresses the goal. Provide constructive feedback."
            "Respond with a JSON object containing 'status' (PASS/FAIL), 'score' (0-100), "
            "and 'feedback' (detailed suggestions for improvement or confirmation of success)."
        ))
        user_message = HumanMessage(content=f"""
        Overall Goal: {overall_goal}

        Provided Context:
        {context}

        Agent's Final Answer:
        {final_answer}

        Please provide your verification status, score, and detailed feedback on the final answer.
        """)
        messages = [system_message, user_message]
        try:
            response = await self.model_router.route("verification", messages)
            feedback = parse_llm_json(response.content)
            logger.info("verifier.final_answer_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.final_answer_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify final answer: {str(e)}"}