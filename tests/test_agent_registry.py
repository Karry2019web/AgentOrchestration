import pytest
from src.agent.registry import AgentRegistry, AgentStatus, CapabilityContract


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


class TestCapabilityContract:
    def test_init_default_schema(self):
        cc = CapabilityContract()
        assert cc.version == 1
        assert cc.contract_hash is not None

    def test_init_with_schema(self):
        cc = CapabilityContract({"actions": ["read", "write"], "max_concurrency": 5})
        assert cc.version == 1
        assert cc.get_schema() == {"actions": ["read", "write"], "max_concurrency": 5}

    def test_update_schema_changes_version(self):
        cc = CapabilityContract({"version": "1.0"})
        old_hash = cc.contract_hash
        assert cc.update_schema({"version": "2.0"})
        assert cc.version == 2
        assert cc.contract_hash != old_hash

    def test_update_schema_identical_no_change(self):
        cc = CapabilityContract({"key": "value"})
        assert not cc.update_schema({"key": "value"})
        assert cc.version == 1

    def test_get_schema_returns_copy(self):
        cc = CapabilityContract({"key": "value"})
        schema = cc.get_schema()
        schema["new_key"] = "new_value"
        assert "new_key" not in cc.get_schema()


class TestStaleContractEnforcement:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_get_returns_none_for_stale_agent(self):
        aid = self.registry.register("agent", "worker")
        assert self.registry.get(aid) is not None
        self.registry.update_contract_schema({"new": "schema"})
        assert self.registry.get(aid) is None

    def test_get_or_invalidate_removes_stale_agent(self):
        aid = self.registry.register("agent", "worker")
        self.registry.update_contract_schema({"new": "schema"})
        result = self.registry.get_or_invalidate(aid)
        assert result is None
        assert self.registry.count() == 0

    def test_list_excludes_stale_agents(self):
        aid1 = self.registry.register("agent-1", "worker")
        aid2 = self.registry.register("agent-2", "worker")
        assert len(self.registry.list()) == 2
        self.registry.update_contract_schema({"v2": True})
        self.registry.register("agent-3", "worker")
        assert len(self.registry.list()) == 1

    def test_update_status_rejected_for_stale_agent(self):
        aid = self.registry.register("agent", "worker")
        self.registry.update_contract_schema({"v2": True})
        assert not self.registry.update_status(aid, AgentStatus.RUNNING)

    def test_invalidate_stale_cleans_multiple(self):
        a1 = self.registry.register("a1", "worker")
        a2 = self.registry.register("a2", "worker")
        a3 = self.registry.register("a3", "worker")
        self.registry.update_contract_schema({"v2": True})
        self.registry.register("a4", "worker")
        count = self.registry.invalidate_stale()
        assert count == 3
        assert self.registry.count() == 1

    def test_invalidate_all_clears_everything(self):
        self.registry.register("a1", "worker")
        self.registry.register("a2", "worker")
        count = self.registry.invalidate_all()
        assert count == 2
        assert self.registry.count() == 0

    def test_fresh_agents_after_contract_update_work_normally(self):
        self.registry.register("old-agent", "worker")
        self.registry.update_contract_schema({"v2": True})
        aid = self.registry.register("new-agent", "worker")
        agent = self.registry.get(aid)
        assert agent is not None
        assert agent["name"] == "new-agent"
        assert self.registry.update_status(aid, AgentStatus.RUNNING)

    def test_contract_version_tracks_changes(self):
        assert self.registry.get_contract_version() == 1
        self.registry.update_contract_schema({"v2": True})
        assert self.registry.get_contract_version() == 2
        self.registry.update_contract_schema({"v3": True})
        assert self.registry.get_contract_version() == 3

    def test_contract_hash_changes_on_update(self):
        h1 = self.registry.get_contract_hash()
        self.registry.update_contract_schema({"new": "schema"})
        h2 = self.registry.get_contract_hash()
        assert h1 != h2
