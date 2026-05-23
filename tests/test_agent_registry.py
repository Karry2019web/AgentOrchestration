import pytest
from src.agent.registry import AgentRegistry, AgentStatus


class TestAgentRegistry:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert agent_id is not None
        assert self.registry.count() == 1

    def test_get_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert agent is not None
        assert agent["name"] == "test-agent"
        assert agent["type"] == "worker.processor"

    def test_get_nonexistent_agent(self):
        agent = self.registry.get("nonexistent-id")
        assert agent is None

    def test_list_agents(self):
        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "worker.analyzer")
        self.registry.register("agent-3", "monitor.watcher")
        assert len(self.registry.list()) == 3

    def test_list_agents_by_group(self):
        self.registry.register("agent-1", "worker.processor")
        self.registry.register("agent-2", "monitor.watcher")
        workers = self.registry.list(group="worker")
        assert len(workers) == 1

    def test_update_status(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.update_status(agent_id, AgentStatus.RUNNING)
        agent = self.registry.get(agent_id)
        assert agent["status"] == "running"

    def test_delete_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.delete(agent_id)
        assert self.registry.count() == 0

    def test_delete_nonexistent_agent(self):
        assert not self.registry.delete("nonexistent-id")

    def test_get_events_empty(self):
        agent_id = self.registry.register("ev-agent", "worker.processor")
        assert self.registry.get_events(agent_id) == []

    def test_add_and_get_events(self):
        agent_id = self.registry.register("ev-agent", "worker.processor")
        self.registry.add_event(agent_id, {"type": "run", "status": "started"})
        self.registry.add_event(agent_id, {"type": "run", "status": "completed"})
        events = self.registry.get_events(agent_id)
        assert len(events) == 2
        assert events[0]["status"] == "started"
        assert events[1]["status"] == "completed"

    def test_get_events_nonexistent_agent(self):
        assert self.registry.get_events("no-such-agent") == []

    def test_add_event_nonexistent_agent_does_not_raise(self):
        self.registry.add_event("no-such-agent", {"type": "run"})
        # Should not raise and nothing stored
        assert True
