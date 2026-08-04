import json
import re
from typing import Any


def parse_llm_json(content: str) -> Any:
    """
    Parse JSON out of an LLM response, tolerating the common case where
    the model wraps its JSON in a markdown code fence, e.g.:

```json
        [ ... ]
```

    or just:
    { ... }

Raises json.JSONDecodeError (same as json.loads) if no valid JSON
    can be extracted, so existing except-blocks that catch that still work.
    """
    text = content.strip()

    # Strip a leading ```json or ``` fence, and a trailing ``` fence, if present.
    fence_match = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    return json.loads(text)