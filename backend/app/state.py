"""
Canonical state schema for Aether's agent execution graph.

All nodes (PlannerNode, ExecutorNode, VerifierNode) must read from and return
a dict that conforms to this TypedDict.  Using TaskState as the single source
of truth prevents nodes from silently adding or dropping fields.
"""
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class CostMetrics(TypedDict):
    kimi_input_tokens: int
    kimi_output_tokens: int
    deepseek_input_tokens: int
    deepseek_output_tokens: int
    total_cost_usd: float
    tool_calls: int


class TaskState(TypedDict, total=False):
    # ── Identity ──────────────────────────────────────────────────────────────
    task_id: str
    task: str           # The user's original task text
    user_id: str
    tenant_id: str

    # ── Message history ───────────────────────────────────────────────────────
    messages: List[str]  # JSON-serialised LangChain messages (via langchain_core.load.dumps)

    # ── Planning ──────────────────────────────────────────────────────────────
    plan: List[Dict[str, Any]]   # Steps produced by PlannerNode
    current_step: int            # Index of the next step to execute
    planning_iterations: int     # Number of times PlannerNode has been called
    feedback: str                # Verifier feedback forwarded to next plan

    # ── Execution ─────────────────────────────────────────────────────────────
    results: List[Dict[str, Any]]  # Collected per-step results
    tool_calls: List[Any]          # Raw tool-call records for auditing
    scratchpad: str                # Working memory / scratch space for agents

    # ── Verification & completion ─────────────────────────────────────────────
    verification: Optional[str]    # Last verifier LLM response
    needs_replan: bool             # Explicit replan flag (set by verifier)
    done: bool                     # True when verifier approves the answer
    final_answer: Optional[str]    # The approved final answer string

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    status: str                    # "pending" | "running" | "done" | "failed"
    cost_metrics: CostMetrics      # Token / cost accounting
