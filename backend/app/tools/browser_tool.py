"""
BrowserTool – Phase 0 search‑enhanced stub.

Uses DuckDuckGo Instant Answer API with retries and an HTML fallback.
Full browser‑use (Playwright) will be added in Phase 1.
"""

import asyncio
import logging

import httpx

from app.tools.registry import BaseTool, ToolSchema

logger = logging.getLogger("aether.tools.browser")


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

        # Common headers to avoid being blocked
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }

        # ---------- Phase 1: Instant Answer API (with retry) ----------
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
                            return {"output": abstract}
                        answer = data.get("Answer")
                        if answer:
                            return {"output": answer}
                        related = data.get("RelatedTopics", [])
                        if related:
                            first = related[0]
                            if isinstance(first, dict) and "Text" in first:
                                return {"output": first["Text"]}
                            elif isinstance(first, str):
                                return {"output": first}
                        # No usable text found; go to fallback
                        break

                    elif resp.status_code == 202:
                        # DuckDuckGo sometimes returns 202 – wait a moment and retry
                        logger.warning(
                            "duckduckgo_202_retry", query=query, attempt=attempt
                        )
                        await asyncio.sleep(1.0)
                        continue  # second attempt

                    else:
                        logger.warning(
                            "duckduckgo_api_bad_status",
                            status=resp.status_code,
                            query=query,
                        )
                        break  # fallback

            except httpx.TimeoutException:
                logger.warning("duckduckgo_timeout", query=query, attempt=attempt)
                await asyncio.sleep(0.5)
                continue
            except Exception as exc:
                logger.error("duckduckgo_api_error", error=str(exc))
                break

        # ---------- Phase 2: HTML fallback ----------
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=15.0
            ) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers=headers,
                )
                if resp.status_code == 200:
                    # Use BeautifulSoup if available, otherwise a simple regex
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(resp.text, "html.parser")
                        snippets = soup.select(".result__snippet")
                        if snippets:
                            return {
                                "output": snippets[0].get_text(strip=True)
                            }
                    except ImportError:
                        # Fallback to a simple regex extraction (less accurate)
                        import re

                        matches = re.findall(
                            r'<a class="result__snippet"[^>]*>([^<]+)',
                            resp.text,
                        )
                        if matches:
                            return {"output": matches[0].strip()}

        except Exception as exc:
            logger.error("duckduckgo_html_fallback_error", error=str(exc))

        return {
            "output": f"No results found for '{query}'. Try rephrasing your query."
        }