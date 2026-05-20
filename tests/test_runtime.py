"""Tests for AgentRuntime - lifecycle runtime with state-machine guards,
durable failure recording, and bounded retries."""

import pytest
import time
from src.agent.runtime import (
    AgentRuntime,
    RuntimeState,
    RuntimeTransition,
    RuntimeFailure,
    MAX_RETRY_COUNT,
)


class TestRuntimeStateMachine:
    """Test state-machine transition guards."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_initial_state_is_stopped(self):
        assert self.runtime.get_state("nonexistent") == RuntimeState.STOPPED

    def test_is_legal_transition(self):
        assert RuntimeTransition.is_legal(RuntimeState.STOPPED, RuntimeState.STARTING)
        assert RuntimeTransition.is_legal(RuntimeState.STARTING, RuntimeState.RUNNING)
        assert RuntimeTransition.is_legal(RuntimeState.RUNNING, RuntimeState.STOPPING)
        assert RuntimeTransition.is_legal(RuntimeState.STOPPING, RuntimeState.STOPPED)
        assert RuntimeTransition.is_legal(RuntimeState.STARTING, RuntimeState.CRASHED)
        assert RuntimeTransition.is_legal(RuntimeState.STOPPING, RuntimeState.CRASHED)

    def test_illegal_transition(self):
        assert not RuntimeTransition.is_legal(RuntimeState.STOPPED, RuntimeState.RUNNING)
        assert not RuntimeTransition.is_legal(RuntimeState.RUNNING, RuntimeState.STARTING)
        assert not RuntimeTransition.is_legal(RuntimeState.CRASHED, RuntimeState.RUNNING)
        assert not RuntimeTransition.is_legal(RuntimeState.STOPPING, RuntimeState.STARTING)


class TestRuntimeFailureRecording:
    """Test that failure reasons are recorded before shutdown."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_failure_recorded_on_start_exception(self):
        # Start with a non-existent command to trigger failure
        result = self.runtime.start("agent-1", ["/nonexistent/binary"])
        assert not result
        failures = self.runtime.get_failures("agent-1")
        assert len(failures) == 1
        assert "Failed to start" in failures[0].reason
        assert failures[0].agent_id == "agent-1"

    def test_durable_state_recorded_before_failure(self):
        self.runtime.start("agent-2", ["/nonexistent/binary"])
        durable = self.runtime.get_durable_state("agent-2")
        assert durable is not None
        assert durable["agent_id"] == "agent-2"

    def test_get_last_failure(self):
        self.runtime.start("agent-3", ["/nonexistent/binary"])
        last = self.runtime.get_last_failure("agent-3")
        assert last is not None
        assert isinstance(last, RuntimeFailure)

    def test_get_last_failure_none(self):
        assert self.runtime.get_last_failure("nonexistent") is None

    def test_get_failures_empty(self):
        assert self.runtime.get_failures("nonexistent") == []

    def test_runtimefailure_to_dict(self):
        failure = RuntimeFailure(
            agent_id="test",
            reason="test reason",
            timestamp=1234567890.0,
            exit_code=-1,
            transition="running",
        )
        d = failure.to_dict()
        assert d["agent_id"] == "test"
        assert d["reason"] == "test reason"
        assert d["exit_code"] == -1
        assert d["transition"] == "running"


class TestRuntimeRetries:
    """Test bounded retry behavior."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_retry_count_starts_at_zero(self):
        assert self.runtime.get_retry_count("agent-1") == 0

    def test_reset_retries(self):
        # Just verify it doesn't error
        self.runtime.reset_retries("agent-1")

    def test_multiple_failures_collected(self):
        for i in range(3):
            self.runtime.start(f"agent-retry", ["/nonexistent/binary"])
        failures = self.runtime.get_failures("agent-retry")
        assert len(failures) == 3
        # But the start() guard prevents > MAX_RETRY_COUNT actual attempts
        # due to the retry count check


class TestRuntimeStateDetection:
    """Test state detection and crash detection."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_clear_failures(self):
        self.runtime.start("agent-clr", ["/nonexistent/binary"])
        assert len(self.runtime.get_failures("agent-clr")) > 0
        self.runtime.clear_failures("agent-clr")
        assert self.runtime.get_failures("agent-clr") == []

    def test_shutdown_all_no_crash(self):
        # Just verify it doesn't raise
        self.runtime.shutdown_all()

    def test_is_running_for_nonexistent(self):
        assert not self.runtime.is_running("nonexistent")


class TestRuntimeTransitionGuard:
    """Test transition guard prevents illegal operations."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_start_during_transitional_state_returns_false(self):
        # Simulate being in STARTING state
        self.runtime._states["agent-blocked"] = RuntimeState.STARTING
        result = self.runtime.start("agent-blocked", ["echo", "hi"])
        assert not result

    def test_stop_already_stopping_returns_false(self):
        self.runtime._states["agent-stop-blocked"] = RuntimeState.STOPPING
        result = self.runtime.stop("agent-stop-blocked")
        assert not result


class TestRuntimeCrashDetection:
    """Test unexpected crash detection on get_state."""

    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_crash_recorded_when_process_dies_unexpectedly(self):
        # Start a process that immediately exits
        import subprocess
        proc = subprocess.Popen(["echo", "hello"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()  # Let it finish

        # Manually inject into runtime with RUNNING state
        self.runtime._processes["agent-crash"] = proc
        self.runtime._states["agent-crash"] = RuntimeState.RUNNING

        # get_state should detect the crash
        state = self.runtime.get_state("agent-crash")
        assert state == RuntimeState.CRASHED

        # Failure should be recorded
        failures = self.runtime.get_failures("agent-crash")
        assert len(failures) == 1
        assert "crashed" in failures[0].reason.lower()

    def test_durable_state_on_crash(self):
        import subprocess
        proc = subprocess.Popen(["echo", "hello"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        proc.wait()
        self.runtime._processes["agent-durable"] = proc
        self.runtime._states["agent-durable"] = RuntimeState.RUNNING
        self.runtime.get_state("agent-durable")

        durable = self.runtime.get_durable_state("agent-durable")
        assert durable is not None
        assert durable["agent_id"] == "agent-durable"


class TestRuntimeDataClasses:
    """Test RuntimeFailure dataclass."""

    def test_runtimefailure_defaults(self):
        failure = RuntimeFailure(
            agent_id="a",
            reason="r",
            timestamp=1.0,
        )
        assert failure.exit_code is None
        assert failure.transition is None

    def test_runtimefailure_full(self):
        failure = RuntimeFailure(
            agent_id="b",
            reason="reason",
            timestamp=2.0,
            exit_code=1,
            transition="running->crashed",
        )
        assert failure.exit_code == 1
        assert failure.transition == "running->crashed"
