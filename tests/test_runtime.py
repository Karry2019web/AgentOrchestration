import pytest
from src.agent.runtime import AgentRuntime, RuntimeState, CompletedState


class TestAgentRuntime:
    def test_initial_state(self):
        runtime = AgentRuntime()
        assert runtime.get_state("non-existent") == RuntimeState.STOPPED

    def test_start_agent(self):
        runtime = AgentRuntime()
        result = runtime.start("agent-1", ["echo", "hello"])
        assert result is True
        assert runtime.is_running("agent-1") is True

    def test_heartbeat_accepted_for_active_run(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        result = runtime.process_heartbeat("agent-1", "run-001")
        assert result is True

    def test_heartbeat_rejected_for_completed_run_finished(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        runtime.complete_run("agent-1", "run-001", CompletedState.FINISHED)

        result = runtime.process_heartbeat("agent-1", "run-001")
        assert result is False

    def test_heartbeat_rejected_for_completed_run_failed(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        runtime.complete_run("agent-1", "run-001", CompletedState.FAILED)

        result = runtime.process_heartbeat("agent-1", "run-001")
        assert result is False

    def test_heartbeat_rejected_for_completed_run_cancelled(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        runtime.complete_run("agent-1", "run-001", CompletedState.CANCELLED)

        result = runtime.process_heartbeat("agent-1", "run-001")
        assert result is False

    def test_heartbeat_rejected_when_agent_not_started(self):
        runtime = AgentRuntime()
        result = runtime.process_heartbeat("ghost-agent", "run-999")
        assert result is False

    def test_heartbeat_rejected_when_agent_crashed(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["nonexistent-command-xyz"], run_id="run-001")
        result = runtime.process_heartbeat("agent-1", "run-001")
        assert result is False

    def test_is_run_completed(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        assert runtime.is_run_completed("run-001") is False

        runtime.complete_run("agent-1", "run-001", CompletedState.FINISHED)
        assert runtime.is_run_completed("run-001") is True

    def test_get_run_state(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        assert runtime.get_run_state("run-001") is None

        runtime.complete_run("agent-1", "run-001", CompletedState.FAILED)
        assert runtime.get_run_state("run-001") == CompletedState.FAILED

    def test_heartbeat_accepted_different_run_ids(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        runtime.complete_run("agent-1", "run-001", CompletedState.FINISHED)

        runtime.start("agent-1", ["sleep", "5"], run_id="run-002")
        result = runtime.process_heartbeat("agent-1", "run-002")
        assert result is True

    def test_start_rejected_for_completed_run(self):
        runtime = AgentRuntime()
        runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        runtime.complete_run("agent-1", "run-001", CompletedState.FINISHED)

        result = runtime.start("agent-1", ["sleep", "5"], run_id="run-001")
        assert result is False

    def test_multiple_completed_runs_tracked_independently(self):
        runtime = AgentRuntime()
        runtime.complete_run("agent-1", "run-001", CompletedState.FINISHED)
        runtime.complete_run("agent-2", "run-002", CompletedState.FAILED)
        runtime.complete_run("agent-3", "run-003", CompletedState.CANCELLED)

        assert runtime.get_run_state("run-001") == CompletedState.FINISHED
        assert runtime.get_run_state("run-002") == CompletedState.FAILED
        assert runtime.get_run_state("run-003") == CompletedState.CANCELLED
