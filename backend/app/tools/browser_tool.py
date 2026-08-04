"""
BrowserTool -- web search backed by the Tavily Search API.

Replaces the earlier DuckDuckGo Instant Answer stub. Tavily is purpose-built
for LLM/agent consumption: results come back as structured JSON with a real
source URL per result, which is exactly what the Verifier has been asking
for when it complains about missing citations.

Note: this tool is named "browser" for now to avoid touching every other
file that references it (planner prompts, executor, tool registry key).
Once real interactive browsing (BrowserAutomationService -- navigate/click/
fill/screenshot) is wired in as its own tool, consider renaming this one to
"web_search" to make the distinction between "search the web" and "drive an
actual browser" clear to the planner.
"""

import os

import httpx
import structlog

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.browser")

TAVILY_API_URL = "https://api.tavily.com/search"


class BrowserTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser",
            description=(
                "Search the web for factual, up-to-date information. Returns a short "
                "synthesized answer plus a list of source results, each with a title, "
                "URL, and content snippet -- use the URLs as citations."
            ),
            parameters={
                "query": {
                    "type": "string",
                    "description": "The search query, e.g., 'current president of South Africa'",
                }
            },
            required=["query"],
            sandbox_template="browser-sandbox",  # Phase 2
        )

    async def execute(self, **kwargs):
        query = kwargs.get("query", "")
        if not query:
            return {"output": "No search query provided."}

        api_key = os.getenv("TAVILY_API_KEY", "").strip()
        if not api_key:
            logger.error("tavily_api_key_missing")
            return {"output": "Search is not configured (missing TAVILY_API_KEY)."}

        payload = {
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
            "include_answer": True,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(TAVILY_API_URL, json=payload, headers=headers)

            if resp.status_code != 200:
                logger.warning("tavily_api_bad_status", status=resp.status_code, query=query)
                return {"output": f"Search failed (status {resp.status_code}). Try rephrasing the query."}

            data = resp.json()
            return {"output": self._format_results(data, query)}

        except httpx.TimeoutException:
            logger.warning("tavily_timeout", query=query)
            return {"output": "Search timed out. Try a more specific query."}
        except Exception:
            logger.exception("tavily_api_error", query=query)
            return {"output": "Search failed due to an unexpected error."}

    def _format_results(self, data: dict, query: str) -> str:
        parts = []

        answer = data.get("answer")
        if answer:
            parts.append(f"Answer: {answer}")

        results = data.get("results", [])
        if not results:
            return "\n".join(parts) if parts else f"No results found for '{query}'."

        parts.append("Sources:")
        for r in results:
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            content = (r.get("content") or "").strip()
            if len(content) > 400:
                content = content[:400].rstrip() + "..."
            parts.append(f"- {title} ({url})\n  {content}")

        return "\n".join(parts)