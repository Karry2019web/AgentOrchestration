"""Tests for AgentRuntime."""

import pytest
from src.agent.runtime import AgentRuntime, RuntimeState


def test_stop_rejects_negative_timeout():
    """A negative timeout should be rejected without looking up or signaling a process."""
    runtime = AgentRuntime()
    agent_id = "test-agent-01"

    # Register the agent as running
    runtime.start(agent_id, ["python", "-c", "import time; time.sleep(30)"])

    # Attempt to stop with negative timeout — should return False immediately
    result = runtime.stop(agent_id, timeout=-1)

    assert result is False, "stop() should return False for negative timeout"
    assert runtime.is_running(agent_id) is True, "Agent should still be running after negative timeout stop attempt"
    assert runtime.get_state(agent_id) == RuntimeState.RUNNING, (
        "Runtime state should remain RUNNING after negative timeout stop attempt"
    )

    # Clean up
    runtime.stop(agent_id, timeout=5)
