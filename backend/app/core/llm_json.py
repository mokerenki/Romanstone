import json
import re
from typing import Any, Union, List, Dict


def parse_llm_json(content: str) -> Union[Dict[str, Any], List[Any]]:
    """
    Parse JSON out of an LLM response, tolerating common issues:
    
    1. Markdown code blocks: ```json ... ``` or ``` ... ```
    2. Text before/after the JSON
    3. Trailing commas
    4. Single quotes instead of double quotes (basic handling)
    5. Missing quotes around keys
    
    Args:
        content: The raw response content from the LLM
        
    Returns:
        Parsed JSON as dict or list
        
    Raises:
        ValueError: If no JSON can be extracted
    """
    if not content or not content.strip():
        raise ValueError("Empty content cannot be parsed as JSON")
    
    text = content.strip()
    
    # ─── Step 1: Try to extract JSON from markdown code blocks ───
    
    # Pattern 1: ```json ... ``` or ``` ... ```
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
        logger.debug("parse_llm_json.extracted_from_fence", preview=text[:100])
    
    # ─── Step 2: If no code block, try to find JSON in the text ───
    else:
        # Try to find JSON starting with { or [
        json_match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", text)
        if json_match:
            text = json_match.group(1).strip()
            logger.debug("parse_llm_json.extracted_from_text", preview=text[:100])
    
    # ─── Step 3: Try to parse as-is ──────────────────────────────
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # ─── Step 4: Try to fix trailing commas ──────────────────────
    try:
        # Remove trailing commas before } or ]
        cleaned = re.sub(r',\s*([}\]])', r'\1', text)
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # ─── Step 5: Try to fix single quotes ────────────────────────
    try:
        # Replace single quotes with double quotes (be careful with apostrophes)
        # This is a basic fix - works for simple cases
        fixed = text.replace("'", '"')
        # Fix any double-double quotes
        fixed = re.sub(r'""', '"', fixed)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # ─── Step 6: Try to fix missing quotes around keys ──────────
    try:
        # Add quotes around unquoted keys: {key: value} -> {"key": value}
        def quote_keys(match):
            return f'"{match.group(1)}":'
        fixed = re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', quote_keys, text)
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # ─── Step 7: Last resort - try to extract anything that looks like JSON ───
    try:
        # Find anything that looks like an array or object
        match = re.search(r'(\[[\s\S]*\]|\{[\s\S]*\})', text)
        if match:
            candidate = match.group(1).strip()
            # Try all fixes on the candidate
            for fix in [
                lambda x: x,
                lambda x: re.sub(r',\s*([}\]])', r'\1', x),
                lambda x: x.replace("'", '"'),
                lambda x: re.sub(r'([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'\1"\2":', x),
            ]:
                try:
                    return json.loads(fix(candidate))
                except:
                    continue
    except:
        pass
    
    # ─── If all fails, raise a descriptive error ──────────────────
    raise ValueError(
        f"Failed to parse JSON from LLM response. "
        f"Content preview: {content[:200]}..."
    )


# Optional: Add a logger for debugging
import structlog
logger = structlog.get_logger("aether.core.llm_json")