import structlog
from langgraph.graph import StateGraph, END
from app.agents.planner import Planner
from app.agents.executor import ExecutorNode
from app.agents.verifier import Verifier
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.tools.registry import ToolRegistry
from app.agents.router import DomainRouter

logger = structlog.get_logger("aether.graph")


def create_graph(
    router: KimiDeepSeekRouter,
    domain_router: DomainRouter,
    registry: ToolRegistry,
    checkpointer=None
):
    graph = StateGraph(dict)

    verifier = Verifier(router)
    planner = Planner(router, domain_router, verifier, registry)
    executor = ExecutorNode(registry, router)

    graph.add_node("planner", planner)
    graph.add_node("executor", executor)
    graph.add_node("verifier", verifier)
    graph.set_entry_point("planner")

    # Generous ceiling: incremented by both planner and executor on every
    # visit, so a normal successful multi-step plan (1 plan + N steps)
    # can legitimately use several of these before anything has gone
    # wrong. This is a backstop against runaway loops, not the primary
    # control on replanning (Planner.max_replans already handles that).
    MAX_PLANNING_ITERATIONS = 20

    def after_planner(state):
        # Planner sets done=True itself once it hits its own max_replans
        # cap. That must be respected here -- otherwise the graph just
        # keeps running the (unchanged, capped) plan through the executor
        # forever.
        if state.get("done", False):
            return END
        return "executor"

    def should_loop(state):
        # Hard stop - always check first
        if state.get("done", False):
            return END
        
        # Check if plan is empty (planner returned [] when max_replans reached)
        if not state.get("plan") or len(state.get("plan", [])) == 0:
            logger.warning("graph.empty_plan", state_keys=list(state.keys()))
            state["done"] = True
            state["status"] = "completed"
            if not state.get("final_answer"):
                results = state.get("results", [])
                state["final_answer"] = (
                    results[-1].get("output") if results
                    else "The task could not be completed. Please try rephrasing your request."
                )
            return END

        if state.get("planning_iterations", 0) >= MAX_PLANNING_ITERATIONS:
            logger.warning("graph.max_iterations_reached", iterations=state.get("planning_iterations"))
            state["done"] = True
            state["status"] = "completed"
            if not state.get("final_answer"):
                results = state.get("results", [])
                state["final_answer"] = (
                    results[-1].get("output") if results
                    else "Task could not be completed within the maximum number of attempts."
                )
            return END

        if state.get("needs_replan", False):
            return "planner"

        # Not done, no replan needed -> this step passed and there are
        # more steps left in the plan. Continue executing, don't restart.
        return "executor"

    graph.add_conditional_edges(
        "planner",
        after_planner,
        {
            "executor": "executor",
            END: END,
        },
    )
    graph.add_edge("executor", "verifier")
    graph.add_conditional_edges(
        "verifier",
        should_loop,
        {
            "planner": "planner",
            "executor": "executor",
            END: END,
        },
    )

    return graph.compile(checkpointer=checkpointer)