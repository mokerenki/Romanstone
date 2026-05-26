"""BrowserTool — Phase 0 stub. Full browser-use integration in Phase 1."""
from app.tools.registry import BaseTool, ToolSchema

class BrowserTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="browser",
            description="Navigate to a URL and perform an action (navigate, click, extract).",
            parameters={
                "url": {"type": "string", "description": "Target URL to navigate to."},
                "action": {"type": "string", "description": "Action: navigate, click, extract."},
            },
            required=["url"],
            sandbox_template="browser-sandbox",  # Phase 2
        )

    async def execute(self, **kwargs):
        url = kwargs.get("url", "about:blank")
        action = kwargs.get("action", "navigate")
        return {
            "output": f"[BrowserTool] {action} on {url} — stub, full integration in Phase 1."
        }