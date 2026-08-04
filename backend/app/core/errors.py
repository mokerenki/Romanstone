from enum import Enum


class TaskErrorCode(str, Enum):
    MODEL_PROVIDER_UNAVAILABLE = "model_provider_unavailable"
    RATE_LIMITED = "rate_limited"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    DEPENDENCIES_NOT_READY = "dependencies_not_ready"
    INTERNAL_ERROR = "internal_error"


def to_user_error(exc: Exception) -> tuple[TaskErrorCode, str]:
    """
    Map an internal exception to a (code, user-safe message) pair.
    The raw exception should still be logged server-side via logger.exception —
    only this tuple goes out over the WebSocket.
    """
    name = type(exc).__name__

    # Match by class name rather than importing every provider SDK's exception
    # types here — keeps this module decoupled from model_router internals.
    if name in ("APIConnectionError", "APITimeoutError", "ConnectionError"):
        return (
            TaskErrorCode.MODEL_PROVIDER_UNAVAILABLE,
            "The AI provider is temporarily unavailable. Please try again shortly.",
        )
    if name in ("RateLimitError",):
        return (
            TaskErrorCode.RATE_LIMITED,
            "You've hit a usage limit. Please try again in a few minutes.",
        )
    if name in ("ToolExecutionError",):
        tool_name = getattr(exc, "tool_name", "a step")
        return (
            TaskErrorCode.TOOL_EXECUTION_FAILED,
            f"The '{tool_name}' step failed. Your task was not completed.",
        )

    return (
        TaskErrorCode.INTERNAL_ERROR,
        "Something went wrong on our end. Our team has been notified.",
    )