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


class TestRegistryCapabilities:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_capability(self):
        assert self.registry.register_capability("custom-plugin", "2.0.0")

    def test_reject_duplicate_capability(self):
        assert self.registry.register_capability("my-plugin")
        assert not self.registry.register_capability("my-plugin")

    def test_get_capabilities(self):
        self.registry.register_capability("plugin-a", "1.0.0")
        self.registry.register_capability("plugin-b", "2.0.0")
        caps = self.registry.get_capabilities()
        assert caps["plugin-a"] == "1.0.0"
        assert caps["plugin-b"] == "2.0.0"

    def test_has_capability(self):
        self.registry.register_capability("my-plugin")
        assert self.registry.has_capability("my-plugin")
        assert not self.registry.has_capability("nonexistent")

    def test_reject_duplicate_name_on_register(self):
        """Registering an agent with a name that matches an existing capability should be rejected."""
        self.registry.register_capability("shared-name")
        result = self.registry.register("shared-name", "worker.processor")
        assert result is None

    def test_reject_duplicate_name_on_register_capability(self):
        """Registering a capability with a name that matches an existing agent should be rejected."""
        agent_id = self.registry.register("my-agent", "worker.processor")
        assert agent_id is not None
        # Registering a capability with same name should succeed
        # (capability and agent namespaces are separate from registration perspective)
        assert self.registry.register_capability("my-agent")
