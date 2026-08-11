import asyncio
from typing import Any, Dict, List, Optional, Set
from langchain_core.messages import HumanMessage  # type: ignore[import-not-found]

from app.tools.registry import ToolRegistry
from app.core.model_router_kimi_deepseek import KimiDeepSeekRouter
from app.core.context_compression import compress_context
from app.core.exceptions import ToolConfirmationRequired

MAX_COST_PER_TASK = 2.0


def _estimate_cost(response: Any) -> float:
    try:
        usage = getattr(response, "usage_metadata", None)
        if not usage:
            return 0.0
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)
        # NOTE: these are DeepSeek's per-token prices, used here because the
        # "fallback" role defaults to DeepSeek. If NVIDIA_API_KEY is set,
        # ModelRouter routes "fallback" to Nvidia instead (see
        # model_router_kimi_deepseek.py) and this will misreport actual
        # spend for that provider. Not fixed here -- flagging so it isn't
        # mistaken for accurate billing telemetry.
        return (input_tokens / 1_000_000) * 0.14 + (output_tokens / 1_000_000) * 0.28
    except Exception:
        return 0.0


def _accumulate_cost(state: dict, added_cost: float) -> None:
    metrics = state.get("cost_metrics", {}) or {}
    metrics["total_cost_usd"] = float(metrics.get("total_cost_usd", 0) or 0) + added_cost
    state["cost_metrics"] = metrics


def _check_cost_ceiling(state: dict) -> bool:
    metrics = state.get("cost_metrics", {}) or {}
    total = float(metrics.get("total_cost_usd", 0) or 0)
    if total > MAX_COST_PER_TASK:
        state["done"] = True
        state["status"] = "completed"
        state["final_answer"] = (
            f"Task stopped because the cost limit of ${MAX_COST_PER_TASK:.2f} "
            f"was reached (current total: ${total:.4f}). "
            "Here is what was gathered so far."
        )
        return True
    return False


class ExecutorNode:
    def __init__(self, registry: ToolRegistry, router: KimiDeepSeekRouter):
        self.registry = registry
        self.router = router

    async def __call__(self, state: dict) -> dict:
        if state.get("done", False):
            return state

        plan = state.get("plan", [])
        current_step = state.get("current_step", 0)
        results = state.get("results", [])

        if not plan or current_step >= len(plan):
            new_state = {**state}
            new_state["results"] = results
            new_state["current_step"] = current_step
            new_state["status"] = "completed"
            new_state["done"] = True
            return new_state

        # ── Build dependency graph ────────────────────────────────
        dependencies: Dict[int, Set[int]] = {}
        for i, step in enumerate(plan):
            deps = step.get("depends_on")
            if deps is None and i > 0:
                dependencies[i] = {i - 1}
            elif deps is None and i == 0:
                dependencies[i] = set()
            else:
                dependencies[i] = set(deps)

        completed_indices = set(range(current_step))
        ready_steps = []
        for i in range(current_step, len(plan)):
            if dependencies[i].issubset(completed_indices):
                ready_steps.append(i)
            else:
                break

        if not ready_steps:
            new_state = {**state}
            new_state["current_step"] = len(plan)
            new_state["status"] = "completed"
            new_state["done"] = True
            return new_state

        skipped_steps = set(state.get("skipped_steps", {}).keys())
        ready_steps = [i for i in ready_steps if i not in skipped_steps]

        if not ready_steps:
            new_state = {**state}
            new_state["current_step"] = len(plan)
            new_state["status"] = "completed"
            new_state["done"] = True
            return new_state

        # ── Execute ready steps in parallel ───────────────────────
        step_futures = [self._execute_step(plan[i], i, state) for i in ready_steps]
        step_results = await asyncio.gather(*step_futures, return_exceptions=True)

        # ─── BUGFIX ────────────────────────────────────────────────
        # `return_exceptions=True` means asyncio.gather() catches EVERY
        # exception raised inside `_execute_step` -- including
        # ToolConfirmationRequired, which `tasks.py` and
        # `websocket_handler.py` both specifically `except` further up
        # the call stack to pause the run and prompt the user.
        #
        # Previously that exception was silently treated the same as any
        # other tool failure a few lines below (folded into
        # `results.append({"output": f"Error executing step {idx}: ..."})`),
        # so it never reached those handlers: the irreversible tool never
        # ran, the user was never shown the confirm/reject prompt, and the
        # agent just saw a generic "step failed" and (often) burned a
        # replan trying to work around a confirmation gate it didn't know
        # existed.
        #
        # Re-raise it here so it propagates out of this node exactly as
        # the caller expects. If more than one parallel step needed
        # confirmation, raise the first one -- the rest are re-attempted
        # on resume once the graph replays from this same current_step.
        for result in step_results:
            if isinstance(result, ToolConfirmationRequired):
                raise result

        for idx, result in zip(ready_steps, step_results):
            if isinstance(result, Exception):
                results.append({
                    "step": plan[idx].get("description", ""),
                    "tool": plan[idx].get("tool_name"),
                    "output": f"Error executing step {idx}: {result}",
                    "step_index": idx,
                })
            else:
                results.append(result)

        for idx in sorted(skipped_steps):
            if idx < len(plan):
                results.append({
                    "step": plan[idx].get("description", ""),
                    "tool": plan[idx].get("tool_name"),
                    "output": "Skipped by user",
                    "step_index": idx,
                })

        results.sort(key=lambda r: r.get("step_index", 0))

        new_current_step = max(ready_steps) + 1
        new_state = {**state}
        new_state["results"] = results
        new_state["current_step"] = new_current_step
        new_state["planning_iterations"] = state.get("planning_iterations", 0) + 1

        # ── Final answer synthesis (with compressed context) ──────
        # This gate only fires when final_answer is falsy. That's now
        # reliably true on every fresh attempt because Verifier clears
        # final_answer whenever it sets needs_replan=True (see the
        # corrected verifier.py) -- previously a failed final answer was
        # left in place across a replan, this gate stayed shut forever,
        # and the verifier kept re-failing the same stale text instead of
        # ever seeing a new one, burning through max_replans for nothing.
        if new_current_step >= len(plan) and not state.get("final_answer"):
            if _check_cost_ceiling(new_state):
                return new_state

            context = compress_context(results, max_total_chars=8000, max_per_result=2000)

            final_prompt = f"""Answer the user's question directly. Default to 1-2 sentences for straightforward factual questions. Only exceed this if the question is genuinely complex or the honest answer requires a brief qualifier.

User's question: {state['task']}

Context from previous steps:
{context}

Rules:
* You are SynthAI 
* You are based in South Africa
* You have a wait list page, and your site is https://synthai.world
* Be factual and direct.
* Base your answer strictly on the information above. Do not fill gaps with general knowledge.
* If the context does not contain enough information, say so plainly in one sentence.
* Give exact names, dates, and numbers when present.
* Do not mention sources unless asked.
* Do not add warnings about information being out of date.
* Plain prose only — no markdown, bullets, JSON, or tool references.
* Answer only what was asked.
* You are in """

            try:
                final_resp = await self.router.route("fallback", [HumanMessage(content=final_prompt)])
                new_state["final_answer"] = final_resp.content
                cost = _estimate_cost(final_resp)
                if cost:
                    _accumulate_cost(new_state, cost)
            except Exception as e:
                new_state["final_answer"] = (
                    results[-1]["output"] if results else f"Could not synthesize a final answer: {e}"
                )

        return new_state

    async def _execute_step(self, step: dict, step_index: int, state: dict) -> dict:
        tool_name = step.get("tool_name")
        description = step.get("description", "Complete the task")

        if tool_name:
            tool = self.registry.get(tool_name)
            if not tool:
                return {
                    "step": description,
                    "tool": tool_name,
                    "output": f"Error: Tool '{tool_name}' not found.",
                    "step_index": step_index,
                }

            # ── Confirmation gating for irreversible tools ─────────
            if tool.schema.irreversible:
                confirmed_tools = state.get("confirmed_tools", {})
                if not confirmed_tools.get(tool_name):
                    raise ToolConfirmationRequired(
                        tool_name=tool_name,
                        tool_args=step.get("tool_args", {}),
                        step_description=description,
                        step_index=step_index,
                    )

            try:
                result = await asyncio.wait_for(
                    tool.execute(**step.get("tool_args", {})),
                    timeout=60.0,
                )
                output = result.get("output", "") if isinstance(result, dict) else str(result)
            except asyncio.TimeoutError:
                output = f"Error executing tool '{tool_name}': timed out after 60s"
            except Exception as e:
                output = f"Error executing tool '{tool_name}': {e}"

            # ── Bulky output truncation ────────────────────────────
            original_len = len(output)
            if original_len > 4000:
                output = output[:3000] + f"\n...[output truncated from {original_len} chars]"

            return {
                "step": description,
                "tool": tool_name,
                "output": output,
                "step_index": step_index,
            }
        else:
            # LLM synthesis step
            context = compress_context(
                state.get("results", []),
                max_total_chars=6000,
                max_per_result=1500,
            )

            prompt = f"""Answer the user's question directly. Default to 1-2 sentences.

User's question: {state['task']}

Context from previous steps:
{context}

Rules:
* You are SynthAI 
* You are based in South Africa
* You have a wait list page, and your site is https://synthai.world
* Be factual and direct.
* If the answer is a simple fact, state it plainl like a human would.
* Base your answer strictly on the information in "Context from previous steps" -- do not fill gaps with your own general knowledge, and do not guess.
* If the context does not contain enough information to answer confidently, say so plainly in one sentence rather than guessing.
* If the context contains conflicting information, prefer the most recent or most authoritative source and answer with that.
* Give exact names, dates, and numbers when the context contains them.
* Do not add warnings about information being out of date.
* Do not include markdown formatting, bullet points, raw JSON, or references to tools/steps -- plain prose only.
* Answer only what was asked."""

            try:
                llm_resp = await self.router.route("fallback", [HumanMessage(content=prompt)])
                output = llm_resp.content
            except Exception as e:
                output = f"Error synthesizing step: {e}"

            return {
                "step": description,
                "output": output,
                "step_index": step_index,
            }