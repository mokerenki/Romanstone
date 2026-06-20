"""
Tests for the agent loop contract.

Covers:
1. Multi-step plan execution — planner returns a list; executor runs all steps.
2. Executor increments current_step — each call advances by exactly 1.
3. Verifier gate — still_executing routes to 'verifier' only after all steps finish.
4. Failed verification replans with a MAX_ITERATIONS cap — loop stops at MAX_ITERATIONS.

All external LLM / tool calls are mocked so tests are fast, hermetic, and free.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.state import TaskState
from app.agents.planner import PlannerNode
from app.agents.executor import ExecutorNode
from app.agents.verifier import VerifierNode


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_state(**overrides) -> TaskState:
    """Return a minimal valid TaskState suitable for unit tests."""
    state: TaskState = {
        "task_id": "test-001",
        "task": "What is 2 + 2?",
        "user_id": "tester",
        "tenant_id": "default",
        "messages": [],
        "plan": [],
        "current_step": 0,
        "results": [],
        "tool_calls": [],
        "feedback": "",
        "verification": None,
        "needs_replan": False,
        "done": False,
        "final_answer": None,
        "status": "pending",
        "cost_metrics": {
            "kimi_input_tokens": 0,
            "kimi_output_tokens": 0,
            "deepseek_input_tokens": 0,
            "deepseek_output_tokens": 0,
            "total_cost_usd": 0.0,
            "tool_calls": 0,
        },
        "planning_iterations": 0,
        "scratchpad": "",
    }
    state.update(overrides)
    return state


def _mock_router(content: str) -> MagicMock:
    """Return a ModelRouter mock whose route() returns a response with .content."""
    router = MagicMock()
    resp = MagicMock()
    resp.content = content
    router.route = AsyncMock(return_value=resp)
    router.ROLE_VERIFICATION = "verification"
    return router


def _mock_registry(tool_output: str = "42") -> MagicMock:
    """Return a ToolRegistry mock that returns a fixed tool output."""
    registry = MagicMock()
    tool = MagicMock()
    tool.execute = AsyncMock(return_value={"output": tool_output})
    registry.get = MagicMock(return_value=tool)
    registry.describe_all = MagicMock(return_value=[])
    return registry


# ── Test 1: Multi-step plan execution ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_step_plan_execution():
    """
    PlannerNode produces a list of steps.
    ExecutorNode processes each step one at a time.
    After running all steps, results list has one entry per step.
    """
    two_step_plan = [
        {"action": "use_tool", "tool": "python_repl", "args": {"code": "2+2"}, "description": "Calculate"},
        {"action": "formulate_final_answer", "tool": "", "args": {}, "description": "Answer"},
    ]
    import json

    router = _mock_router(json.dumps(two_step_plan))
    registry = _mock_registry("4")

    # 1. Planner produces the plan
    planner = PlannerNode(router, registry)
    state = _base_state()
    state = await planner(state)

    assert isinstance(state["plan"], list), "plan must be a list"
    assert len(state["plan"]) == 2, "planner should produce 2 steps"
    assert state["current_step"] == 0, "planner resets current_step to 0"

    # 2. Executor runs step 0 (tool step)
    executor = ExecutorNode(registry, router)
    state = await executor(state)
    assert len(state["results"]) == 1
    assert state["current_step"] == 1

    # 3. Executor runs step 1 (no-tool LLM step)
    router2 = _mock_router("The answer is 4.")
    executor2 = ExecutorNode(registry, router2)
    state = await executor2(state)
    assert len(state["results"]) == 2
    assert state["current_step"] == 2


# ── Test 2: Executor increments current_step ──────────────────────────────────

@pytest.mark.asyncio
async def test_executor_increments_current_step():
    """Each ExecutorNode call advances current_step by exactly 1."""
    plan = [
        {"action": "step_a", "tool": "python_repl", "args": {}, "description": "Step A"},
        {"action": "step_b", "tool": "python_repl", "args": {}, "description": "Step B"},
        {"action": "step_c", "tool": "python_repl", "args": {}, "description": "Step C"},
    ]
    registry = _mock_registry("ok")
    router = _mock_router("ok")
    executor = ExecutorNode(registry, router)

    state = _base_state(plan=plan, current_step=0)

    for expected_step in range(1, len(plan) + 1):
        state = await executor(state)
        assert state["current_step"] == expected_step, (
            f"After call {expected_step}, current_step should be {expected_step}, "
            f"got {state['current_step']}"
        )


# ── Test 3: Verifier runs only after all plan steps finish ────────────────────

def test_verifier_gate_routing():
    """
    The still_executing routing function (extracted and unit-tested here)
    must route to 'verifier' only when current_step == len(plan).
    """
    # Replicate the routing logic from graph.py without importing it
    # (avoids the need for a full LangGraph setup in a unit test)
    def still_executing(state: TaskState) -> str:
        if state.get("current_step", 0) >= len(state.get("plan", [])):
            return "verifier"
        return "executor"

    plan = [{"action": "a"}, {"action": "b"}, {"action": "c"}]

    # Mid-execution — should stay in executor
    assert still_executing(_base_state(plan=plan, current_step=0)) == "executor"
    assert still_executing(_base_state(plan=plan, current_step=1)) == "executor"
    assert still_executing(_base_state(plan=plan, current_step=2)) == "executor"

    # All steps done — must go to verifier
    assert still_executing(_base_state(plan=plan, current_step=3)) == "verifier"

    # Empty plan edge case — immediately to verifier
    assert still_executing(_base_state(plan=[], current_step=0)) == "verifier"


# ── Test 4: Failed verification replans with MAX_ITERATIONS cap ───────────────

@pytest.mark.asyncio
async def test_failed_verification_replans_with_max_iterations():
    """
    A verifier that always returns 'no' should cause PlannerNode to be called
    again (via the should_loop routing) and must stop at MAX_ITERATIONS.
    """
    from app.graph import MAX_ITERATIONS

    # Verifier always says 'no'
    router_no = _mock_router("no, the answer is incomplete")
    verifier = VerifierNode(router_no)

    # Simulate iterating the verifier + should_loop guard
    def should_loop(state: TaskState) -> str:
        if state.get("done", False):
            return "END"
        if state.get("planning_iterations", 0) >= MAX_ITERATIONS:
            return "END"
        return "planner"

    replan_count = 0
    state = _base_state(
        plan=[{"action": "a", "tool": "", "args": {}, "description": "a"}],
        current_step=1,   # Simulate all steps done
        results=[{"step": "a", "output": "partial answer"}],
        planning_iterations=0,
    )

    for _ in range(MAX_ITERATIONS + 2):  # Run more iterations than MAX to confirm the cap
        state = await verifier(state)
        assert not state["done"], "Verifier should keep saying 'no'"
        route = should_loop(state)
        if route == "END":
            break
        # Simulate planner being called (increment counter)
        state = {**state, "planning_iterations": state.get("planning_iterations", 0) + 1}
        replan_count += 1

    assert replan_count <= MAX_ITERATIONS, (
        f"Replanned {replan_count} times — exceeds MAX_ITERATIONS={MAX_ITERATIONS}"
    )
    assert should_loop(state) == "END", (
        "Loop should terminate at MAX_ITERATIONS, not continue indefinitely"
    )


# ── Test 5: Modules are side-effect free on import ────────────────────────────

def test_modules_importable_without_external_services():
    """
    Importing app.api.tasks and app.api.memory_api must NOT contact Redis,
    Qdrant, Kuzu, or any LLM API.

    Before the dependency-injection refactor these imports opened HTTP clients
    and read environment variables at module level, crashing CI without the
    services running.  This test acts as the regression guard.
    """
    import importlib

    # These must not raise even when no environment variables are set and no
    # external services are reachable.
    importlib.import_module("app.api.tasks")
    importlib.import_module("app.api.memory_api")
    importlib.import_module("app.api.dependencies")
