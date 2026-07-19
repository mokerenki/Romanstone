import structlog
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.agents.verifier import Verifier
from app.agents.router import DomainRouter

logger = structlog.get_logger("aether.agents.planner")


class Planner:
    def __init__(self, model_router: KimiDeepSeekRouter, domain_router: DomainRouter, verifier: Verifier, max_replans: int = 3):
        self.model_router = model_router
        self.domain_router = domain_router
        self.verifier = verifier
        self.max_replans = max_replans
        self.current_plan: List[Dict[str, Any]] = []
        self.replan_count = 0
        logger.info("planner.initialized", max_replans=max_replans)

    async def generate_plan(self, overall_goal: str, context: str, image_data: Optional[str] = None,
                            user_id: str = "anonymous", thread_id: str = "default") -> List[Dict[str, Any]]:
        """Generate plan with domain routing."""
        logger.info("planner.generating_initial_plan", goal=overall_goal[:100], has_image=bool(image_data))

        route_result = await self.domain_router.route(overall_goal, user_id, thread_id)
        domain = route_result["domain"]
        domain_context = route_result["context"]
        system_prompt = route_result["system_prompt"]

        domain_tools = self._get_domain_tools(domain_context)
        tools_description = self._format_tools_description(domain_tools)

        system_message = SystemMessage(content=(
            f"{system_prompt}\n\n"
            "Your task is to create a detailed, actionable plan to achieve a given overall goal. "
            "Break down the goal into sequential steps. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, use 'tool_name': 'None'. "
            f"Available tools: {tools_description} "
            "Respond with a JSON array of step objects."
        ))

        user_message_content = f"""
        Overall Goal: {overall_goal}

        Context:
        {context}

        Domain Context:
        {json.dumps(domain_context, indent=2)}

        Create a detailed plan (JSON array of steps) to achieve this goal.
        """
        user_message = HumanMessage(content=user_message_content)
        messages = [system_message, user_message]

        try:
            response = await self.model_router.route("planning", messages, model="kimi", image_data=image_data)
            plan = json.loads(response.content)
            self.current_plan = plan
            logger.info("planner.initial_plan_generated", num_steps=len(plan), domain=domain)
            return plan
        except Exception as e:
            logger.error("planner.initial_plan_failed", error=str(e), exc_info=True)
            return []

    async def replan(self, overall_goal: str, context: str, feedback: Dict[str, Any], image_data: Optional[str] = None,
                     user_id: str = "anonymous", thread_id: str = "default") -> List[Dict[str, Any]]:
        """Replan with domain routing."""
        if self.replan_count >= self.max_replans:
            logger.warning("planner.max_replans_reached", replan_count=self.replan_count)
            return self.current_plan

        self.replan_count += 1
        logger.info("planner.replanning", goal=overall_goal[:100], replan_count=self.replan_count, has_image=bool(image_data))

        route_result = await self.domain_router.route(overall_goal, user_id, thread_id)
        domain = route_result["domain"]
        domain_context = route_result["context"]
        system_prompt = route_result["system_prompt"]

        domain_tools = self._get_domain_tools(domain_context)
        tools_description = self._format_tools_description(domain_tools)

        system_message = SystemMessage(content=(
            f"{system_prompt}\n\n"
            "Your task is to revise an existing plan based on critical feedback from a Verifier. "
            "The goal is to create a more effective and accurate plan to achieve the overall goal. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, use 'tool_name': 'None'. "
            f"Available tools: {tools_description} "
            "Respond with a JSON array of revised step objects."
        ))

        user_message_content = f"""
        Overall Goal: {overall_goal}

        Context:
        {context}

        Domain Context:
        {json.dumps(domain_context, indent=2)}

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
            logger.info("planner.revised_plan_generated", num_steps=len(revised_plan), replan_count=self.replan_count, domain=domain)
            return revised_plan
        except Exception as e:
            logger.error("planner.replan_failed", error=str(e), exc_info=True)
            return self.current_plan

    def get_current_plan(self) -> List[Dict[str, Any]]:
        return self.current_plan

    def reset_replan_count(self):
        self.replan_count = 0
        logger.debug("planner.replan_count_reset")

    def _get_domain_tools(self, domain_context: Dict[str, Any]) -> List[str]:
        """Get domain-specific tools from context."""
        return domain_context.get("available_tools", ["python_repl_secure", "browser", "memory_retriever"])

    def _format_tools_description(self, tools: List[str]) -> str:
        """Format tools for the planner prompt."""
        return ", ".join([f"'{tool}'" for tool in tools])
