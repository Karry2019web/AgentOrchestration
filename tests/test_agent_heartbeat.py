"""Tests for worker heartbeat guard — preventing revival of completed runs."""

import time
import pytest
from src.agent.registry import AgentRegistry, AgentStatus, _TERMINAL_STATUSES


class TestHeartbeatGuard:
    def setup_method(self):
        self.registry = AgentRegistry()
        self.agent_id = self.registry.register("test-agent", "worker")

    def test_heartbeat_accepted_for_pending(self):
        """Pending agents accept heartbeats."""
        assert self.registry.record_heartbeat(self.agent_id) is True
        agent = self.registry.get(self.agent_id)
        assert agent["last_heartbeat"] is not None

    def test_heartbeat_accepted_for_running(self):
        """Running agents accept heartbeats."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        assert self.registry.record_heartbeat(self.agent_id) is True
        agent = self.registry.get(self.agent_id)
        assert agent["last_heartbeat"] is not None

    def test_heartbeat_refused_for_stopped(self):
        """Stopped agents must NOT be revived by heartbeat."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        self.registry.record_heartbeat(self.agent_id)
        self.registry.update_status(self.agent_id, AgentStatus.STOPPED)
        assert self.registry.record_heartbeat(self.agent_id) is False

    def test_heartbeat_refused_for_failed(self):
        """Failed agents must NOT be revived by heartbeat."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        self.registry.record_heartbeat(self.agent_id)
        self.registry.update_status(self.agent_id, AgentStatus.FAILED)
        assert self.registry.record_heartbeat(self.agent_id) is False

    def test_heartbeat_refused_for_terminated(self):
        """Terminated agents must NOT be revived by heartbeat."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        self.registry.record_heartbeat(self.agent_id)
        self.registry.update_status(self.agent_id, AgentStatus.TERMINATED)
        assert self.registry.record_heartbeat(self.agent_id) is False

    def test_heartbeat_refused_for_nonexistent(self):
        """Non-existent agents return False."""
        assert self.registry.record_heartbeat("nonexistent-id") is False

    def test_is_terminal_true_for_stopped(self):
        """is_terminal returns True for stopped agents."""
        self.registry.update_status(self.agent_id, AgentStatus.STOPPED)
        assert self.registry.is_terminal(self.agent_id) is True

    def test_is_terminal_false_for_running(self):
        """is_terminal returns False for running agents."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        assert self.registry.is_terminal(self.agent_id) is False

    def test_is_terminal_true_for_nonexistent(self):
        """is_terminal returns True for non-existent agents."""
        assert self.registry.is_terminal("ghost") is True

    def test_heartbeat_updates_timestamp(self):
        """Heartbeat records the current timestamp."""
        self.registry.update_status(self.agent_id, AgentStatus.RUNNING)
        before = time.time()
        time.sleep(0.001)
        self.registry.record_heartbeat(self.agent_id)
        after = time.time()
        agent = self.registry.get(self.agent_id)
        assert before <= agent["last_heartbeat"] <= after

    def test_terminal_statuses_are_exhaustive(self):
        """Ensure all terminal states are covered."""
        terminal = {AgentStatus.STOPPED, AgentStatus.FAILED, AgentStatus.TERMINATED}
        assert _TERMINAL_STATUSES == terminal
