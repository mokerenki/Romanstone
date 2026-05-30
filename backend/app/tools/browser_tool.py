"""
BrowserTool – Phase 0 search‑enhanced stub.

Uses DuckDuckGo Instant Answer API with retries and HTML fallback.
Full browser‑use (Playwright) will be added in Phase 1.
"""

import asyncio
import structlog

import httpx

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.browser")


class BrowserTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser",
            description="Look up factual information on the web. Provide a search query.",
            parameters={
                "query": {
                    "type": "string",
                    "description": "The search query, e.g., 'current president of South Africa'",
                }
            },
            required=["query"],
            sandbox_template="browser-sandbox",  # Phase 2
        )

    async def execute(self, **kwargs):
        query = kwargs.get("query", "")
        if not query:
            return {"output": "No search query provided."}

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        # Phase 1: Instant Answer API (with retry on 202)
        api_url = "https://api.duckduckgo.com/"
        api_params = {
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        }

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=12.0
                ) as client:
                    resp = await client.get(
                        api_url, params=api_params, headers=headers
                    )

                    if resp.status_code == 200:
                        data = resp.json()
                        abstract = data.get("AbstractText")
                        if abstract:
                            return {"output": self._clean_snippet(abstract, query)}
                        answer = data.get("Answer")
                        if answer:
                            return {"output": self._clean_snippet(answer, query)}
                        related = data.get("RelatedTopics", [])
                        if related:
                            first = related[0]
                            if isinstance(first, dict) and "Text" in first:
                                return {"output": self._clean_snippet(first["Text"], query)}
                            elif isinstance(first, str):
                                return {"output": self._clean_snippet(first, query)}
                        # No usable text, go to fallback
                        break

                    elif resp.status_code == 202:
                        logger.warning("duckduckgo_202_retry", query=query, attempt=attempt)
                        await asyncio.sleep(1.0)
                        continue

                    else:
                        logger.warning("duckduckgo_api_bad_status", status=resp.status_code, query=query)
                        break

            except httpx.TimeoutException:
                logger.warning("duckduckgo_timeout", query=query, attempt=attempt)
                await asyncio.sleep(0.5)
                continue
            except Exception as exc:
                logger.exception("duckduckgo_api_error")
                break

        # Phase 2: HTML fallback
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers=headers,
                )
                if resp.status_code == 200:
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(resp.text, "html.parser")
                        snippets = soup.select(".result__snippet")
                        if snippets:
                            return {"output": self._clean_snippet(snippets[0].get_text(strip=True), query)}
                    except ImportError:
                        import re
                        matches = re.findall(
                            r'<a class="result__snippet"[^>]*>([^<]+)',
                            resp.text,
                        )
                        if matches:
                            return {"output": self._clean_snippet(matches[0].strip(), query)}
        except Exception as exc:
            logger.exception("duckduckgo_html_fallback_error")

        return {"output": f"No results found for '{query}'. Try rephrasing your query."}

    def _clean_snippet(self, text: str, query: str) -> str:
        """Ensure the snippet is a self‑contained sentence."""
        if not text:
            return text
        # If text starts with a lowercase or a pronoun, prepend the query
        if text[0].islower() or text.startswith(("He ", "She ", "It ", "They ")):
            text = f"{query} – {text}"
        # Add a period if missing
        if not text.endswith(('.', '!', '?')):
            text += '.'
        return text.strip()