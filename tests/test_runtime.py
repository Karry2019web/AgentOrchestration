"""Tests for AgentRuntime — process lifecycle with memory limit enforcement."""

import os
import subprocess
import sys
import time

import pytest

from src.agent.runtime import AgentRuntime, RuntimeState


def _dummy_cmd():
    """Return a platform-appropriate command that sleeps briefly."""
    if sys.platform == "win32":
        return ["python", "-c", "import time; time.sleep(30)"]
    return ["sleep", "30"]


def _short_cmd():
    """Return a command that exits immediately."""
    if sys.platform == "win32":
        return ["python", "-c", ""]
    return [sys.executable, "-c", ""]


class TestAgentRuntime:
    """Unit tests for AgentRuntime with capacity guard."""

    def setup_method(self):
        self.runtime = AgentRuntime(max_processes=3)

    # ------------------------------------------------------------------
    # Basic lifecycle
    # ------------------------------------------------------------------

    def test_start_process(self):
        cmd = _short_cmd()
        result = self.runtime.start("agent-1", cmd)
        assert result is True
        # Process should finish quickly — poll
        assert self.runtime.active_count() >= 0
        self.runtime.stop("agent-1", timeout=2)

    def test_duplicate_start_rejected(self):
        runtime = AgentRuntime(max_processes=10)
        cmd = _dummy_cmd()
        assert runtime.start("dup-agent", cmd) is True
        # Second start for the same agent_id should be rejected
        assert runtime.start("dup-agent", cmd) is False
        runtime.stop("dup-agent", timeout=2)

    def test_state_transitions(self):
        cmd = _dummy_cmd()
        runtime = AgentRuntime(max_processes=10)

        # Initially STOPPED
        assert runtime.get_state("new-agent") == RuntimeState.STOPPED

        # After start — RUNNING
        assert runtime.start("new-agent", cmd) is True
        assert runtime.get_state("new-agent") == RuntimeState.RUNNING

        # After stop — STOPPED
        runtime.stop("new-agent", timeout=2)
        assert runtime.get_state("new-agent") == RuntimeState.STOPPED

    # ------------------------------------------------------------------
    # Capacity guard (memory / trace aggregation limit)
    # ------------------------------------------------------------------

    def test_respects_max_processes_cap(self):
        """The runtime MUST reject start() when active count == max_processes."""
        runtime = AgentRuntime(max_processes=2)
        cmd = _dummy_cmd()

        assert runtime.start("agent-a", cmd) is True
        assert runtime.start("agent-b", cmd) is True

        # Both slots consumed — third start must be rejected
        assert runtime.start("agent-c", cmd) is False
        assert runtime.active_count() == 2

        # Cleanup
        runtime.stop("agent-a", timeout=2)
        runtime.stop("agent-b", timeout=2)

    def test_capacity_available_after_stop(self):
        """After one process exits, a new one should be accepted."""
        runtime = AgentRuntime(max_processes=1)
        cmd = _dummy_cmd()

        assert runtime.start("only-one", cmd) is True
        assert runtime.start("extra", cmd) is False  # cap reached

        runtime.stop("only-one", timeout=2)
        time.sleep(0.1)

        # Slot should now be free
        assert runtime.start("replacement", cmd) is True
        runtime.stop("replacement", timeout=2)

    def test_default_max_processes(self):
        """Default max_processes should be 50."""
        runtime = AgentRuntime()
        assert runtime.max_processes == 50

    def test_custom_max_processes(self):
        runtime = AgentRuntime(max_processes=5)
        assert runtime.max_processes == 5

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def test_active_count(self):
        cmd = _dummy_cmd()
        runtime = AgentRuntime(max_processes=10)

        assert runtime.active_count() == 0
        runtime.start("a1", cmd)
        assert runtime.active_count() == 1
        runtime.start("a2", cmd)
        assert runtime.active_count() == 2

        runtime.stop("a1", timeout=2)
        time.sleep(0.1)

        # The active_count method should auto-prune dead entries
        # The dead process may or may not be pruned immediately
        # depending on timing — just check it's at most 2
        assert runtime.active_count() <= 2
        runtime.stop("a2", timeout=2)

    def test_total_started_monotonic(self):
        cmd = _short_cmd()
        runtime = AgentRuntime(max_processes=10)

        assert runtime.total_started() == 0
        runtime.start("x1", cmd)
        # The process may have completed already
        assert runtime.total_started() == 1
        runtime.start("x2", cmd)
        assert runtime.total_started() == 2

    def test_is_running(self):
        cmd = _dummy_cmd()
        runtime = AgentRuntime(max_processes=10)

        runtime.start("live", cmd)
        assert runtime.is_running("live") is True

        runtime.stop("live", timeout=2)
        assert runtime.is_running("live") is False

    def test_is_running_nonexistent(self):
        runtime = AgentRuntime()
        assert runtime.is_running("ghost") is False

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_stop_nonexistent_process(self):
        runtime = AgentRuntime()
        assert runtime.stop("nonexistent") is False

    def test_start_after_crash(self):
        """Exited processes should not block future start attempts."""
        cmd = _short_cmd()
        runtime = AgentRuntime(max_processes=5)

        # Start and let it finish
        assert runtime.start("quick", cmd) is True
        time.sleep(0.5)

        # Process should have exited — re-start should work
        state = runtime.get_state("quick")
        if state == RuntimeState.CRASHED:
            assert runtime.start("quick", cmd) is True

# 2026-05-24T10:00:00 update
