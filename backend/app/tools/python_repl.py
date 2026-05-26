"""PythonREPLTool — Phase 0 stub."""
from app.tools.registry import BaseTool, ToolSchema

class PythonREPLTool(BaseTool):
    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="python_repl",
            description="Execute Python code and capture stdout.",
            parameters={
                "code": {"type": "string", "description": "Python code to execute."},
            },
            required=["code"],
            sandbox_template="terminal-sandbox",
        )

    async def execute(self, **kwargs):
        code = kwargs.get("code", "")
        # Phase 0: limited local execution. Phase 2: sandbox.
        import io, sys, traceback
        old = sys.stdout
        sys.stdout = io.StringIO()
        try:
            exec(code)
            output = sys.stdout.getvalue()
        except Exception:
            output = traceback.format_exc()
        finally:
            sys.stdout = old
        return {"output": output}