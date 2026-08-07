import structlog
import json
from typing import Dict, Any, List, Optional
from langchain_core.messages import HumanMessage, SystemMessage  # type: ignore[import-not-found]
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.agents.router import DomainRouter
from app.tools.registry import ToolRegistry
from app.agents.verifier import Verifier
from app.core.llm_json import parse_llm_json

logger = structlog.get_logger("aether.agents.planner")

class Planner:
    def __init__(
        self,
        model_router: KimiDeepSeekRouter,
        domain_router: DomainRouter,
        verifier: Verifier,
        tool_registry: ToolRegistry,
        max_replans: int = 3
    ):
        self.model_router = model_router
        self.domain_router = domain_router
        self.verifier = verifier
        self.tool_registry = tool_registry
        self.max_replans = max_replans
        self.current_plan: List[Dict[str, Any]] = []
        self.replan_count = 0
        logger.info("planner.initialized", max_replans=max_replans)

    async def __call__(self, state: dict) -> dict:
        """LangGraph node entry point."""
        logger.info("planner.called")

        overall_goal = state.get("task", "")
        context = self._build_context(state)
        user_id = state.get("user_id", "anonymous")
        thread_id = state.get("thread_id", "default")
        image_data = state.get("image_data")

        # Check if we need to replan
        if state.get("needs_replan", False):
            feedback = (
                state.get("replan_feedback")
                or state.get("feedback")
                or state.get("verification")
                or {}
            )
            plan = await self.replan(overall_goal, context, feedback, image_data)
            if self.replan_count >= self.max_replans:
                state["done"] = True
                state["status"] = "completed"
                if not state.get("final_answer"):
                    state["final_answer"] = await self._synthesize_fallback_answer(state)
        else:
            self.replan_count = 0
            plan = await self.generate_plan(overall_goal, context, image_data, user_id, thread_id)
        # Update state
        state["plan"] = plan
        state["current_step"] = 0
        state["needs_replan"] = False
        state["planning_iterations"] = state.get("planning_iterations", 0) + 1
        return state

    def _build_context(self, state: dict) -> str:
        parts = []
        if state.get("results"):
            parts.append("Previous Results:")
            for r in state["results"]:
                if isinstance(r, dict):
                    parts.append(f"  - {r.get('step', '')}: {r.get('output', '')}")
                else:
                    parts.append(f"  - {r}")
        return "\n".join(parts)

    async def generate_plan(
        self,
        overall_goal: str,
        context: str,
        image_data: Optional[str] = None,
        user_id: str = "anonymous",
        thread_id: str = "default"
    ) -> List[Dict[str, Any]]:
        # Route to domain
        route_result = await self.domain_router.route(overall_goal, user_id, thread_id)
        domain = route_result["domain"]
        domain_context = route_result["context"]
        system_prompt = route_result["system_prompt"]

        tool_schemas = self.tool_registry.describe_all()
        tools_description = json.dumps(tool_schemas, indent=2)

        system_message = SystemMessage(content=(
            system_prompt + "\n\n" +
            "You are an expert AI Planner. Your task is to create a detailed, actionable plan "
            "to achieve a given overall goal. Break down the goal into sequential steps. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, set 'tool_name' to null. "
            "Respond with a JSON array of step objects. "
            f"Available tools (with their exact required parameters — use these exact "
            f"argument names in tool_args, do not invent your own): {tools_description}"
        ))

        user_message = HumanMessage(content=f"""
        Overall Goal: {overall_goal}

        Context:
        {context}

        Domain Context:
        {json.dumps(domain_context, indent=2) if domain_context else "None"}

        Create a detailed plan (JSON array of steps) to achieve this goal.
        """)
        messages = [system_message, user_message]

        try:
            response = await self.model_router.route("planning", messages)
            plan = parse_llm_json(response.content)
            self.current_plan = plan
            logger.info("planner.initial_plan_generated", num_steps=len(plan), domain=domain)
            return plan
        except Exception as e:
            logger.error("planner.initial_plan_failed", error=str(e), exc_info=True)
            return []

    async def replan(self, overall_goal: str, context: str, feedback: Dict[str, Any], image_data: Optional[str] = None) -> List[Dict[str, Any]]:
        if self.replan_count >= self.max_replans:
            logger.warning("planner.max_replans_reached", replan_count=self.replan_count)
            return self.current_plan

        self.replan_count += 1
        logger.info("planner.replanning", goal=overall_goal[:100], replan_count=self.replan_count)

        system_message = SystemMessage(content=(
            "You are an expert AI Planner. Your task is to revise an existing plan "
            "based on critical feedback from a Verifier. "
            "Each step should be a JSON object with 'step_id', 'description', 'tool_name', "
            "and 'tool_args' (a dictionary). If no tool is needed, set 'tool_name' to null. "
            "Consider the provided context, visual information, and especially the feedback."
            "Respond with a JSON array of revised step objects."
            f"Available tools (with their exact required parameters — use these exact "
            f"argument names in tool_args, do not invent your own): "
            f"{json.dumps(self.tool_registry.describe_all(), indent=2)}"
        ))

        user_message = HumanMessage(content=f"""
        Overall Goal: {overall_goal}

        Context:
        {context}

        Previous Plan:
        {json.dumps(self.current_plan, indent=2)}

        Verifier Feedback:
        {json.dumps(feedback, indent=2)}

        Based on the feedback, create a REVISED detailed plan (JSON array of steps) to achieve this goal.
        """)
        messages = [system_message, user_message]

        try:
            response = await self.model_router.route("planning", messages)
            revised_plan = parse_llm_json(response.content)
            self.current_plan = revised_plan
            logger.info("planner.revised_plan_generated", num_steps=len(revised_plan), replan_count=self.replan_count)
            return revised_plan
        except Exception as e:
            logger.error("planner.replan_failed", error=str(e), exc_info=True)
            return self.current_plan

    async def _synthesize_fallback_answer(self, state: dict) -> str:
        """
        Called when the replan cap is hit with no verified final answer yet.
        Synthesizes the agent's best attempt from whatever was actually
        gathered, instead of returning a static placeholder string.
        """
        results = state.get("results", [])
        if not results:
            return (
                "I wasn't able to find a confident answer to this within the "
                "allotted attempts. You may want to try rephrasing the question "
                "or breaking it into smaller parts."
            )

        context_parts = []
        for r in results:
            if isinstance(r, dict):
                context_parts.append(f"Step: {r.get('step', '')}\nResult: {r.get('output', '')}")
            else:
                context_parts.append(str(r))
        context = "\n\n".join(context_parts)

        prompt = f"""Based on everything gathered below, give the best possible answer to the
user's original question, even if the information is incomplete or not fully verified.
Be upfront and concise about any uncertainty rather than omitting it. Do not include raw
JSON, tool names, or step numbers -- write a direct, well-written answer.

User's original question: {state.get('task', '')}

Gathered information:
{context}
"""
        try:
            response = await self.model_router.route("fallback", [HumanMessage(content=prompt)])
            return response.content
        except Exception as exc:
            logger.error("planner.fallback_synthesis_failed", error=str(exc), exc_info=True)
            # last resort: the most recent raw result, better than nothing
            return results[-1].get("output", "Task could not be completed.") if isinstance(results[-1], dict) else str(results[-1])

    def get_current_plan(self) -> List[Dict[str, Any]]:
        return self.current_plan

    def reset_replan_count(self):
        self.replan_count = 0