from langgraph.graph import StateGraph, END
from app.agents.planner import Planner
from app.agents.executor import ExecutorNode
from app.agents.verifier import Verifier
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.tools.registry import ToolRegistry
from app.agents.router import DomainRouter

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
    graph.add_edge("planner", "executor")
    graph.add_edge("executor", "verifier")

    def should_loop(state):
        if state.get("done", False):
            return END
        else:
            return "planner"

    graph.add_conditional_edges("verifier", should_loop)

    return graph.compile(checkpointer=checkpointer)