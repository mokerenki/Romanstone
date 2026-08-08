from typing import Any, Dict, List, Union


def compress_context(
    results: List[Union[Dict[str, Any], str]],
    max_total_chars: int = 5000,
    max_per_result: int = 1200,
) -> str:
    """
    Build a "Previous Results" context string from a task's accumulated
    step results, keeping it bounded on two axes:

    - max_per_result: caps any single step's output so one bulky tool
      result (e.g. a large page of search results) can't dominate the
      whole context.
    - max_total_chars: caps the combined string. If capping individual
      results still isn't enough, older entries are dropped first (most
      recent steps are usually most relevant to what happens next),
      replaced with a short note so it's clear something was omitted.
    """
    if not results:
        return ""

    formatted: List[str] = []
    for r in results:
        if isinstance(r, dict):
            step = r.get("step", "")
            output = str(r.get("output", ""))
        else:
            step = ""
            output = str(r)

        if len(output) > max_per_result:
            output = output[:max_per_result].rstrip() + "...[truncated]"

        entry = f"  - {step}: {output}" if step else f"  - {output}"
        formatted.append(entry)

    header = "Previous Results:"
    body = "\n".join(formatted)
    full_text = f"{header}\n{body}"

    if len(full_text) <= max_total_chars:
        return full_text

    # Still too long even after per-result capping -- drop oldest entries
    # first, keeping the most recent ones intact, until it fits.
    dropped = 0
    kept = list(formatted)
    while kept and len(f"{header}\n" + "\n".join(kept)) > max_total_chars:
        kept.pop(0)
        dropped += 1

    note = f"  - [{dropped} earlier step(s) omitted for length]" if dropped else ""
    parts = [header]
    if note:
        parts.append(note)
    parts.append("\n".join(kept))
    return "\n".join(p for p in parts if p)