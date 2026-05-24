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


class TestAgentRegistryWorkspaceScope:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_with_workspace(self):
        agent_id = self.registry.register("test-agent", "worker.processor", workspace_id="ws-1")
        agent = self.registry.get(agent_id)
        assert agent["workspace_id"] == "ws-1"

    def test_get_scoped_allowed(self):
        agent_id = self.registry.register("test-agent", "worker.processor", workspace_id="ws-1")
        agent = self.registry.get_scoped(agent_id, "ws-1")
        assert agent is not None
        assert agent["name"] == "test-agent"

    def test_get_scoped_wrong_workspace(self):
        agent_id = self.registry.register("test-agent", "worker.processor", workspace_id="ws-1")
        agent = self.registry.get_scoped(agent_id, "ws-2")
        assert agent is None

    def test_list_with_workspace_filter(self):
        self.registry.register("agent-1", "worker", workspace_id="ws-1")
        self.registry.register("agent-2", "worker", workspace_id="ws-1")
        self.registry.register("agent-3", "worker", workspace_id="ws-2")
        assert len(self.registry.list(workspace_id="ws-1")) == 2
        assert len(self.registry.list(workspace_id="ws-2")) == 1

    def test_count_by_workspace(self):
        self.registry.register("agent-1", "worker", workspace_id="ws-1")
        self.registry.register("agent-2", "worker", workspace_id="ws-2")
        assert self.registry.count(workspace_id="ws-1") == 1
        assert self.registry.count(workspace_id="ws-2") == 1

    def test_update_status_scoped_allowed(self):
        agent_id = self.registry.register("test-agent", "worker", workspace_id="ws-1")
        assert self.registry.update_status_scoped(agent_id, AgentStatus.RUNNING, "ws-1")
        agent = self.registry.get(agent_id)
        assert agent["status"] == "running"

    def test_update_status_scoped_wrong_workspace(self):
        agent_id = self.registry.register("test-agent", "worker", workspace_id="ws-1")
        assert not self.registry.update_status_scoped(agent_id, AgentStatus.RUNNING, "ws-2")

    def test_delete_scoped_allowed(self):
        agent_id = self.registry.register("test-agent", "worker", workspace_id="ws-1")
        assert self.registry.delete_scoped(agent_id, "ws-1")
        assert self.registry.count() == 0

    def test_delete_scoped_wrong_workspace(self):
        agent_id = self.registry.register("test-agent", "worker", workspace_id="ws-1")
        assert not self.registry.delete_scoped(agent_id, "ws-2")
        assert self.registry.count() == 1

    def test_cross_workspace_isolation(self):
        ws1_id = self.registry.register("agent", "worker", workspace_id="ws-1")
        ws2_id = self.registry.register("agent", "worker", workspace_id="ws-2")
        assert ws1_id != ws2_id
        assert len(self.registry.list(workspace_id="ws-1")) == 1
        assert len(self.registry.list(workspace_id="ws-2")) == 1
        assert len(self.registry.list(workspace_id="ws-3")) == 0
