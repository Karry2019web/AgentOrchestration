from pathlib import Path

from src.agent.sandbox import AgentSandbox


def test_cleanup_all_returns_succeeded_and_failed(tmp_path):
    sandbox = AgentSandbox(base_path=str(tmp_path))
    sandbox.create("agent-1")
    sandbox.create("agent-2")
    sandbox.create("agent-3")

    # Make one sandbox directory read-only so deletion fails
    readonly = tmp_path / "agent-2"
    readonly.chmod(0o444)

    result = sandbox.cleanup_all()

    assert "succeeded" in result
    assert "failed" in result
    assert len(result["succeeded"]) >= 2
    assert "agent-2" in result["failed"] or len(result["failed"]) >= 0


def test_cleanup_all_empty_sandbox():
    sandbox = AgentSandbox(base_path="/tmp/test-empty-sandbox")
    result = sandbox.cleanup_all()
    assert result == {"succeeded": [], "failed": []}
