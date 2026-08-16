"""Request-local identity used by user-scoped n8n MCP tools."""

from contextvars import ContextVar

current_integration_user: ContextVar[str] = ContextVar("current_integration_user", default="anonymous")
