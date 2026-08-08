"""Custom exceptions for the Aether agent loop."""

class ToolConfirmationRequired(Exception):
    """Raised when an irreversible tool requires human confirmation before execution."""

    def __init__(self, tool_name: str, tool_args: dict, step_description: str, step_index: int):
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.step_description = step_description
        self.step_index = step_index
        super().__init__(f"Confirmation required for irreversible tool: {tool_name}")