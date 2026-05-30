from langgraph.graph import StateGraph, END
from app.agents.planner import PlannerNode
from app.agents.executor import ExecutorNode
from app.agents.verifier import VerifierNode
from app.core.model_router import ModelRouter
from app.tools.registry import ToolRegistry

def create_graph(router: ModelRouter, registry: ToolRegistry, checkpointer=None):
    graph = StateGraph(dict)

    planner = PlannerNode(router, registry)
    executor = ExecutorNode(registry, router)
    verifier = VerifierNode(router)

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