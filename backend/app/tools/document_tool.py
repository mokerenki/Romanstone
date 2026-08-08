"""
DocumentTool - Generate Markdown/HTML documents and write them to disk.
"""

import os
from typing import Any, Dict

import structlog

from app.tools.registry import BaseTool, ToolSchema

logger = structlog.get_logger("aether.tools.document")


class DocumentTool(BaseTool):
    def __init__(self):
        super().__init__()
        self.output_dir = os.getenv("DOCUMENT_OUTPUT_DIR", "/tmp/aether/documents")
        os.makedirs(self.output_dir, exist_ok=True)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="document",
            description="Generate a Markdown or HTML document and save it to a file.",
            parameters={
                "title": {"type": "string", "description": "Document title (used as filename base)"},
                "content": {"type": "string", "description": "Document body content"},
                "format": {"type": "string", "enum": ["md", "html"], "description": "Output format (default: md)"},
            },
            required=["title", "content"],
            irreversible=False,
        )

    async def execute(self, **kwargs) -> Dict[str, Any]:
        title = kwargs.get("title", "document")
        content = kwargs.get("content", "")
        fmt = kwargs.get("format", "md")
        safe_title = "".join(c if c.isalnum() or c in "._- " else "_" for c in title).strip().replace(" ", "_")
        filename = f"{safe_title}.{fmt}"
        path = os.path.join(self.output_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            logger.info("document.created", path=path, size=len(content))
            return {"output": f"Document saved to {path}", "path": path}
        except Exception as exc:
            logger.error("document.create_failed", error=str(exc))
            return {"output": f"Error creating document: {exc}"}
