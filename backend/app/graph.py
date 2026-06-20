import os

from langgraph.graph import StateGraph, END
from app.agents.planner import PlannerNode
from app.agents.executor import ExecutorNode
from app.agents.verifier import VerifierNode
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry
from app.state import TaskState

# Maximum number of planner → executor → verifier cycles before we force-stop.
# Reads from the environment so deployments can tune without a code change.
MAX_ITERATIONS: int = int(os.environ.get("MAX_PLANNING_ITERATIONS", "3"))


def create_graph(router: ModelRouter, registry: ToolRegistry, checkpointer=None):
    graph = StateGraph(TaskState)

    planner = PlannerNode(router, registry)
    executor = ExecutorNode(registry, router)
    verifier = VerifierNode(router)

    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("verifier", verifier)
    graph.set_entry_point("planner")
    graph.add_edge("planner", "executor")

    def still_executing(state: TaskState) -> str:
        """Route back to executor until every plan step has been run."""
        if state.get("current_step", 0) >= len(state.get("plan", [])):
            return "verifier"
        return "executor"

    graph.add_conditional_edges("executor", still_executing)

    def should_loop(state: TaskState) -> str:
        """
        After verification:
        - If the answer is approved → END.
        - If we have hit MAX_ITERATIONS → END (fail-safe against infinite loops).
        - Otherwise → replan.
        """
        if state.get("done", False):
            return END
        if state.get("planning_iterations", 0) >= MAX_ITERATIONS:
            # Hard stop: prevent runaway replanning.
            return END
        return "planner"

    graph.add_conditional_edges("verifier", should_loop)

    return graph.compile(checkpointer=checkpointer)