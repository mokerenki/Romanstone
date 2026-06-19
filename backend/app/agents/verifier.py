import structlog
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter

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

    async def verify_plan(self, plan: List[Dict[str, Any]], overall_goal: str) -> Dict[str, Any]:
        """
        Verifies the generated plan against the overall goal.
        
        Args:
            plan: The list of steps in the plan.
            overall_goal: The high-level objective.
            
        Returns:
            A dictionary with verification status and feedback.
        """
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
            response = await self.model_router.route("verification", messages, model="kimi")
            feedback = json.loads(response.content)
            logger.info("verifier.plan_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.plan_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify plan: {str(e)}"}

    async def verify_step_output(self, step: Dict[str, Any], step_output: Any, expected_outcome: str) -> Dict[str, Any]:
        """
        Verifies the output of a single step against its expected outcome.
        
        Args:
            step: The step definition.
            step_output: The actual output of the step.
            expected_outcome: The expected result or impact of the step.
            
        Returns:
            A dictionary with verification status and feedback.
        """
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
            response = await self.model_router.route("verification", messages, model="kimi")
            feedback = json.loads(response.content)
            logger.info("verifier.step_output_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.step_output_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify step output: {str(e)}"}

    async def verify_final_answer(self, overall_goal: str, final_answer: str, context: str) -> Dict[str, Any]:
        """
        Verifies the final answer against the overall goal and provided context.
        
        Args:
            overall_goal: The high-level objective.
            final_answer: The agent's proposed final answer.
            context: Relevant context or observations.
            
        Returns:
            A dictionary with verification status and feedback.
        """
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
            response = await self.model_router.route("verification", messages, model="kimi")
            feedback = json.loads(response.content)
            logger.info("verifier.final_answer_verified", status=feedback.get("status"), score=feedback.get("score"))
            return feedback
        except Exception as e:
            logger.error("verifier.final_answer_verification_failed", error=str(e), exc_info=True)
            return {"status": "ERROR", "score": 0, "feedback": f"Failed to verify final answer: {str(e)}"}
