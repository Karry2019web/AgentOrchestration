import pytest
from src.agent.registry import AgentRegistry, AgentStatus, _validate_handler_name


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


class TestHandlerNameValidation:
    def test_validate_empty_name(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_handler_name("")

    def test_validate_none_name(self):
        with pytest.raises(ValueError, match="non-empty string"):
            _validate_handler_name(None)

    def test_validate_valid_name(self):
        _validate_handler_name("my-handler")
        _validate_handler_name("worker.processor")
        _validate_handler_name("agent_42")

    def test_reject_double_dot_prefix(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_handler_name("../etc/passwd")

    def test_reject_double_dot_slash(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_handler_name("plugins/../../../malicious")

    def test_reject_double_dot_backslash(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_handler_name("plugins\\..\\..\\malicious")

    def test_reject_double_dot_suffix(self):
        with pytest.raises(ValueError, match="path traversal"):
            _validate_handler_name("safe/..")

    def test_register_rejects_path_traversal(self):
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="path traversal"):
            registry.register("../../malicious", "worker.processor")

    def test_register_rejects_type_with_path_traversal(self):
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="path traversal"):
            registry.register("safe-name", "../../malicious")

    def test_resolve_rejects_path_traversal(self):
        registry = AgentRegistry()
        with pytest.raises(ValueError, match="path traversal"):
            registry.resolve("../etc/passwd")
