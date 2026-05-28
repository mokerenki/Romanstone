"""
BrowserTool – Phase 0 search-enhanced stub.

For now, uses a free DuckDuckGo instant answer API for simple factual queries.
Full browser‑use (Playwright) will be added in Phase 1.
"""

import httpx
from app.tools.registry import BaseTool, ToolSchema


class BrowserTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser",
            description="Look up factual information on the web. Provide a search query.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "The search query, e.g., 'current president of South Africa'"
                }
            },
            required=["query"],
            sandbox_template="browser-sandbox",  # Phase 2
        )

    async def execute(self, **kwargs):
        query = kwargs.get("query", "")
        if not query:
            return {"output": "No search query provided."}

        # Use DuckDuckGo Instant Answer API (free, no API key needed)
        url = "https://api.duckduckgo.com/"
        params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, params=params, timeout=10.0)
            if resp.status_code != 200:
                return {"output": f"Search request failed with status {resp.status_code}."}
            data = resp.json()

        # Extract the most useful text
        abstract = data.get("AbstractText")
        if abstract:
            return {"output": abstract}

        answer = data.get("Answer")
        if answer:
            return {"output": answer}

        # Fallback: related topics
        related = data.get("RelatedTopics", [])
        if related:
            first = related[0]
            if isinstance(first, dict) and "Text" in first:
                return {"output": first["Text"]}
            elif isinstance(first, str):
                return {"output": first}

        return {"output": f"No results found for '{query}'."}