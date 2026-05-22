"""Tests for AgentRegistry with handler version validation."""

import pytest
from src.agent.registry import AgentRegistry, AgentStatus
from src.agent.handler_version import HandlerVersionError


class TestAgentRegistry:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert agent_id is not None
        assert self.registry.count() == 1

    def test_register_with_version(self):
        agent_id = self.registry.register("test-agent", "worker.processor", version="2.1.0")
        assert agent_id is not None
        agent = self.registry.get(agent_id)
        assert agent["version"] == "2.1.0"

    def test_register_invalid_version_raises_error(self):
        with pytest.raises(HandlerVersionError):
            self.registry.register("bad-agent", "worker.processor", version="0.0.0")

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
        assert agent["status"] == AgentStatus.RUNNING.value

    def test_delete_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.delete(agent_id)
        assert self.registry.count() == 0

    def test_delete_nonexistent_agent(self):
        assert not self.registry.delete("nonexistent-id")

    def test_update_version_safe_upgrade(self):
        agent_id = self.registry.register("test-agent", "worker", version="1.0.0")
        assert self.registry.update_version(agent_id, "1.1.0") is True
        agent = self.registry.get(agent_id)
        assert agent["version"] == "1.1.0"

    def test_update_version_unsafe_upgrade_raises_error(self):
        agent_id = self.registry.register("test-agent", "worker", version="1.0.0")
        with pytest.raises(HandlerVersionError):
            self.registry.update_version(agent_id, "2.0.0")

    def test_update_version_nonexistent_agent(self):
        with pytest.raises(ValueError):
            self.registry.update_version("no-such-agent", "1.1.0")

    def test_resolve_handler_by_name(self):
        self.registry.register("my-agent", "worker", version="1.0.0")
        agent_id = self.registry.resolve_handler("my-agent")
        assert agent_id is not None
        agent = self.registry.get(agent_id)
        assert agent["name"] == "my-agent"

    def test_resolve_nonexistent_handler(self):
        agent_id = self.registry.resolve_handler("nonexistent")
        assert agent_id is None

    def test_get_handler_registry(self):
        hr = self.registry.get_handler_registry()
        assert hr is not None
        assert hasattr(hr, "register")
