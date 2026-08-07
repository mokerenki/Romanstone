import asyncio

from app.sandbox.manager import SandboxManager


class DummySandbox:
    sandbox_id = "dummy-sandbox"

    def create_code_context(self):
        return {"id": "dummy-context"}

    def kill(self):
        return None


def test_create_uses_code_interpreter_template(monkeypatch):
    captured = {}

    def fake_create(*, template=None, timeout=None, metadata=None, **kwargs):
        captured["template"] = template
        return DummySandbox()

    monkeypatch.setattr("app.sandbox.manager._get_e2b_api_key", lambda: "fake-key")
    monkeypatch.setattr("app.sandbox.manager.Sandbox.create", fake_create)

    manager = SandboxManager()
    asyncio.run(manager.create("task-1"))

    assert captured["template"] == "code-interpreter-v1"
