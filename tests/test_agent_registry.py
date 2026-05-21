"""Tests for case-insensitive alias normalization in AgentRegistry."""

import pytest
from src.agent.registry import AgentRegistry, AgentStatus, normalize_alias


class TestNormalizeAlias:
    def test_lowercase(self):
        assert normalize_alias("WORKER.PROCESSOR") == "worker.processor"

    def test_mixed_case(self):
        assert normalize_alias("Worker.Processor") == "worker.processor"

    def test_with_whitespace(self):
        assert normalize_alias("  Worker.Processor  ") == "worker.processor"

    def test_empty_string(self):
        assert normalize_alias("") == ""

    def test_none_like(self):
        assert normalize_alias("") == ""
        assert normalize_alias(None) == ""

    def test_already_lowercase(self):
        assert normalize_alias("worker.processor") == "worker.processor"


class TestAgentRegistryCaseInsensitive:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_normalizes_type(self):
        """Registration stores normalized type for case-insensitive lookup."""
        agent_id = self.registry.register("test-agent", "Worker.Processor")
        agent = self.registry.get(agent_id)
        assert agent is not None
        assert agent["normalized_type"] == "worker.processor"

    def test_find_by_type_case_insensitive(self):
        """Lookup by type name should match regardless of case."""
        self.registry.register("agent-1", "Worker.Processor")
        results = self.registry.find_by_type("WORKER.PROCESSOR")
        assert len(results) == 1
        assert results[0]["name"] == "agent-1"

    def test_find_by_type_lowercase(self):
        self.registry.register("agent-1", "Worker.Processor")
        results = self.registry.find_by_type("worker.processor")
        assert len(results) == 1

    def test_find_by_type_mixed_case(self):
        self.registry.register("agent-1", "Worker.Processor")
        results = self.registry.find_by_type("WoRkEr.ProCeSsOr")
        assert len(results) == 1

    def test_find_by_name_case_insensitive(self):
        """Lookup by name should be case-insensitive."""
        self.registry.register("My-Agent", "worker.processor")
        agent = self.registry.find_by_name("my-agent")
        assert agent is not None
        assert agent["name"] == "My-Agent"

    def test_find_by_name_mixed_case(self):
        self.registry.register("My-Agent", "worker.processor")
        agent = self.registry.find_by_name("MY-AGENT")
        assert agent is not None

    def test_has_type_case_insensitive(self):
        self.registry.register("agent-1", "Worker.Processor")
        assert self.registry.has_type("WORKER.PROCESSOR")
        assert self.registry.has_type("worker.processor")
        assert not self.registry.has_type("monitor.watcher")

    def test_register_multiple_agents_different_types(self):
        """Different types should be independently findable."""
        id1 = self.registry.register("agent-1", "Worker.Processor")
        id2 = self.registry.register("agent-2", "Monitor.Watcher")
        id3 = self.registry.register("agent-3", "worker.helper")

        assert len(self.registry.find_by_type("WORKER.PROCESSOR")) == 1
        assert len(self.registry.find_by_type("monitor.watcher")) == 1
        assert len(self.registry.find_by_type("monitor.Watcher")) == 1

    def test_delete_cleans_alias_cache(self):
        """Deleting an agent should invalidate the alias cache."""
        self.registry.register("agent-1", "Worker.Processor")
        agent = self.registry.find_by_name("agent-1")
        assert agent is not None
        self.registry.delete(agent["id"])
        assert not self.registry.has_type("Worker.Processor")
        assert self.registry.find_by_name("agent-1") is None

    def test_list_by_group_case_insensitive(self):
        """Group listing should be case-insensitive."""
        self.registry.register("agent-1", "Worker.Processor")
        self.registry.register("agent-2", "Monitor.Watcher")
        self.registry.register("agent-3", "worker.helper")

        workers = self.registry.list(group="WORKER")
        assert len(workers) == 2

        monitors = self.registry.list(group="monitor")
        assert len(monitors) == 1

    def test_register_does_not_override_existing_lowercase(self):
        """Register with same normalized alias should create separate IDs."""
        id1 = self.registry.register("agent-1", "Worker.Processor")
        id2 = self.registry.register("agent-2", "worker.processor")

        assert id1 != id2
        # Different names = different agents
        agent1 = self.registry.get(id1)
        agent2 = self.registry.get(id2)
        assert agent1 is not None
        assert agent2 is not None

    def test_existing_tests_still_pass(self):
        """Backward compatibility with original test cases."""
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert agent_id is not None
        assert self.registry.count() == 1

        agent = self.registry.get(agent_id)
        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["type"] == "worker.processor"

        assert self.registry.get("nonexistent-id") is None

        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "worker.analyzer")
        self.registry.register("agent-3", "monitor.watcher")
        assert len(self.registry.list()) == 4  # 3 new + 1 from test-agent above
        # Actually let's start fresh
        self.registry.clear()

    def test_clear_and_clean_state(self):
        """Verify clear() removes all state."""
        self.registry.register("agent-1", "Worker.Processor")
        assert self.registry.count() == 1
        self.registry.clear()
        assert self.registry.count() == 0
        assert not self.registry.has_type("Worker.Processor")
        assert len(self.registry.list()) == 0

    def test_find_by_type_nonexistent(self):
        """Finding by nonexistent type returns empty list."""
        assert self.registry.find_by_type("nonexistent.type") == []

    def test_find_by_type_empty_string(self):
        assert self.registry.find_by_type("") == []

    def test_update_status_preserves_normalized_type(self):
        """Status update should not affect normalized type."""
        agent_id = self.registry.register("agent-1", "Worker.Processor")
        self.registry.update_status(agent_id, AgentStatus.RUNNING)
        assert self.registry.has_type("WORKER.PROCESSOR")
        results = self.registry.find_by_type("worker.processor")
        assert len(results) == 1
        assert results[0]["status"] == "running"

    def test_list_by_status_and_group_case_insensitive(self):
        """Combined filtering with case-insensitive group."""
        id1 = self.registry.register("agent-1", "Worker.Processor")
        id2 = self.registry.register("agent-2", "Worker.Helper")
        id3 = self.registry.register("agent-3", "Monitor.Watcher")

        self.registry.update_status(id1, AgentStatus.RUNNING)
        self.registry.update_status(id2, AgentStatus.PAUSED)

        running_workers = self.registry.list(status=AgentStatus.RUNNING, group="WORKER")
        assert len(running_workers) == 1
        assert running_workers[0]["name"] == "agent-1"
