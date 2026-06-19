import structlog
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.agents.verifier import Verifier

logger = structlog.get_logger("aether.agents.planner")

class Planner:
    """
    The Planner node is responsible for breaking down complex goals into actionable steps.
    It can generate initial plans, and critically, replan based on feedback from the Verifier.
    """

    def __init__(self, model_router: KimiDeepSeekRouter, verifier: Verifier, max_replans: int = 3):
        self.model_router = model_router
        self.verifier = verifier
        self.max_replans = max_replans
        self.current_plan: List[Dict[str, Any]] = []
        self.replan_count = 0
        logger.info("planner.initialized", max_replans=max_replans)

    async def generate_plan(self, overall_goal: str, context: str, image_data: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Generates an initial plan to achieve the overall goal.
        
        Args:
            overall_goal: The high-level objective.
            context: Relevant context or observations.
            image_data: Optional base64 encoded image data for multi-modal planning.
            
        Returns:
            A list of dictionaries, each representing a step in the plan.
        """
        logger.info("planner.generating_initial_plan", goal=overall_goal[:100], has_image=bool(image_data))

        system_message = SystemMessage(content=(
            "You are an expert AI Planner. Your task is to create a detailed, actionable plan "
            "to achieve a given overall goal. Break down the goal into sequential steps. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, use 'tool_name': 'None'."
            "Consider the provided context and any visual information."
            "Respond with a JSON array of step objects."
            "Available tools: ['python_repl_secure', 'browser_automation_service', 'cognee_memory_search', 'cognee_memory_ingest']"
            "Example step: {'step_id': 1, 'description': 'Search for legal precedents', 'tool_name': 'cognee_memory_search', 'tool_args': {'query': 'legal precedents for contract law', 'mode': 'semantic'}}"
        ))
        
        user_message_content = f"""
        Overall Goal: {overall_goal}
        
        Context:
        {context}
        
        Create a detailed plan (JSON array of steps) to achieve this goal.
        """
        user_message = HumanMessage(content=user_message_content)
        
        messages = [system_message, user_message]
        
        try:
            response = await self.model_router.route("planning", messages, model="kimi", image_data=image_data)
            plan = json.loads(response.content)
            self.current_plan = plan
            logger.info("planner.initial_plan_generated", num_steps=len(plan))
            return plan
        except Exception as e:
            logger.error("planner.initial_plan_failed", error=str(e), exc_info=True)
            return []

    async def replan(self, overall_goal: str, context: str, feedback: Dict[str, Any], image_data: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Generates a revised plan based on verifier feedback.
        
        Args:
            overall_goal: The high-level objective.
            context: Relevant context or observations.
            feedback: Structured feedback from the Verifier.
            image_data: Optional base64 encoded image data for multi-modal replanning.
            
        Returns:
            A list of dictionaries, each representing a step in the revised plan.
        """
        if self.replan_count >= self.max_replans:
            logger.warning("planner.max_replans_reached", replan_count=self.replan_count)
            return self.current_plan # Return the last plan if max replans reached

        self.replan_count += 1
        logger.info("planner.replanning", goal=overall_goal[:100], replan_count=self.replan_count, has_image=bool(image_data))

        system_message = SystemMessage(content=(
            "You are an expert AI Planner. Your task is to revise an existing plan "
            "based on critical feedback from a Verifier. The goal is to create a more "
            "effective and accurate plan to achieve the overall goal. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, use 'tool_name': 'None'."
            "Consider the provided context, visual information, and especially the feedback."
            "Respond with a JSON array of revised step objects."
            "Available tools: ['python_repl_secure', 'browser_automation_service', 'cognee_memory_search', 'cognee_memory_ingest']"
        ))
        
        user_message_content = f"""
        Overall Goal: {overall_goal}
        
        Context:
        {context}
        
        Previous Plan:
        {json.dumps(self.current_plan, indent=2)}
        
        Verifier Feedback:
        {json.dumps(feedback, indent=2)}
        
        Based on the feedback, create a REVISED detailed plan (JSON array of steps) to achieve this goal.
        """
        user_message = HumanMessage(content=user_message_content)
        
        messages = [system_message, user_message]
        
        try:
            response = await self.model_router.route("planning", messages, model="kimi", image_data=image_data)
            revised_plan = json.loads(response.content)
            self.current_plan = revised_plan
            logger.info("planner.revised_plan_generated", num_steps=len(revised_plan), replan_count=self.replan_count)
            return revised_plan
        except Exception as e:
            logger.error("planner.replan_failed", error=str(e), exc_info=True)
            return self.current_plan # Fallback to previous plan on error

    def get_current_plan(self) -> List[Dict[str, Any]]:
        """
        Returns the most recently generated or revised plan.
        """
        return self.current_plan

    def reset_replan_count(self):
        """
        Resets the replan count, typically after a successful execution or new goal.
        """
        self.replan_count = 0
        logger.debug("planner.replan_count_reset")
