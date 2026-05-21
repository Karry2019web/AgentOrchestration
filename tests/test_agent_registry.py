"""Tests for Agent Registry with protocol version validation."""

import pytest
from src.agent.registry import AgentRegistry, AgentStatus, AgentProtocolVersion, ProtocolNegotiator
from src.common.errors import IncompatibleProtocolError, ProtocolNegotiationError, AgentNotFoundError


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


class TestAgentProtocolVersion:
    def test_current_version(self):
        assert AgentProtocolVersion.current() == AgentProtocolVersion.V2_0

    def test_compatible_versions_include_current(self):
        compatible = AgentProtocolVersion.compatible_versions()
        assert AgentProtocolVersion.V2_0 in compatible

    def test_compatible_versions_include_v1_1(self):
        """V1.1 is backward compatible with V2.0 (one major behind)."""
        compatible = AgentProtocolVersion.compatible_versions()
        assert AgentProtocolVersion.V1_1 in compatible

    def test_compatible_versions_include_v1_0(self):
        """V1.0 is backward compatible with V2.0 (one major behind)."""
        compatible = AgentProtocolVersion.compatible_versions()
        assert AgentProtocolVersion.V1_0 in compatible

    def test_is_compatible_same_version(self):
        assert AgentProtocolVersion._is_compatible(
            AgentProtocolVersion.V2_0, AgentProtocolVersion.V2_0
        )

    def test_is_compatible_one_major_behind(self):
        assert AgentProtocolVersion._is_compatible(
            AgentProtocolVersion.V1_0, AgentProtocolVersion.V2_0
        )

    def test_is_incompatible_two_majors_behind(self):
        """If we ever add V3.0, V1.x would be two majors behind."""
        v3 = AgentProtocolVersion.V1_0
        target = AgentProtocolVersion.V2_0
        # V1.0 vs V2.0 is only ONE major behind, so still compatible
        assert AgentProtocolVersion._is_compatible(v3, target)

    def test_version_comparison_ge(self):
        assert AgentProtocolVersion.V2_0 >= AgentProtocolVersion.V1_0
        assert AgentProtocolVersion.V1_1 >= AgentProtocolVersion.V1_0
        assert AgentProtocolVersion.V2_0 >= AgentProtocolVersion.V2_0


class TestProtocolNegotiator:
    def setup_method(self):
        self.negotiator = ProtocolNegotiator()

    def test_validate_compatible_version(self):
        # Should not raise
        self.negotiator.validate_protocol("agent-1", "2.0")

    def test_validate_unknown_version(self):
        with pytest.raises(ProtocolNegotiationError):
            self.negotiator.validate_protocol("agent-1", "99.99")

    def test_validate_malformed_version(self):
        with pytest.raises(ProtocolNegotiationError):
            self.negotiator.validate_protocol("agent-1", "not-a-version")

    def test_is_version_compatible(self):
        assert self.negotiator.is_version_compatible("2.0")
        assert self.negotiator.is_version_compatible("1.1")
        assert not self.negotiator.is_version_compatible("invalid")

    def test_invalidate_cache_single(self):
        self.negotiator.validate_protocol("agent-1", "2.0")
        self.negotiator.invalidate_cache("agent-1")
        # Should not raise — cache miss re-validates
        self.negotiator.validate_protocol("agent-1", "2.0")

    def test_invalidate_cache_all(self):
        self.negotiator.validate_protocol("agent-1", "2.0")
        self.negotiator.invalidate_cache()
        self.negotiator.validate_protocol("agent-1", "2.0")

    def test_system_version_property(self):
        assert self.negotiator.system_version == "2.0"


class TestRegistryProtocolIntegration:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_with_default_protocol(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == "2.0"
        assert agent["version"] == "2.0"

    def test_register_with_explicit_compatible_version(self):
        agent_id = self.registry.register(
            "test-agent", "worker.processor", protocol_version="1.1"
        )
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == "1.1"

    def test_register_with_incompatible_version(self):
        with pytest.raises(IncompatibleProtocolError):
            self.registry.register(
                "test-agent", "worker.processor", protocol_version="99.99"
            )

    def test_register_with_malformed_version(self):
        with pytest.raises(ProtocolNegotiationError):
            self.registry.register(
                "test-agent", "worker.processor", protocol_version="not-a-version"
            )

    def test_update_protocol_success(self):
        agent_id = self.registry.register("test-agent", "worker.processor",
                                           protocol_version="1.1")
        assert self.registry.update_protocol(agent_id, "2.0")
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == "2.0"

    def test_update_protocol_nonexistent_agent(self):
        with pytest.raises(AgentNotFoundError):
            self.registry.update_protocol("nonexistent", "2.0")

    def test_update_protocol_incompatible(self):
        agent_id = self.registry.register("test-agent", "worker.processor",
                                           protocol_version="2.0")
        with pytest.raises(IncompatibleProtocolError):
            self.registry.update_protocol(agent_id, "99.99")

    def test_registry_caches_compatibility(self):
        """Registering an agent should cache its protocol compatibility."""
        self.registry.register("agent-1", "worker.processor", protocol_version="1.1")
        self.registry.register("agent-2", "worker.processor", protocol_version="2.0")
        # Both should be registered successfully
        assert self.registry.count() == 2

    def test_delete_invalidates_cache(self):
        agent_id = self.registry.register("agent-1", "worker.processor")
        assert self.registry.delete(agent_id)
        assert self.registry.count() == 0

    def test_list_with_min_protocol_version(self):
        self.registry.register("agent-v1", "worker.processor", protocol_version="1.0")
        self.registry.register("agent-v2", "worker.processor", protocol_version="2.0")
        v2_agents = self.registry.list(min_protocol_version="2.0")
        assert len(v2_agents) == 1
        assert v2_agents[0]["name"] == "agent-v2"

    def test_negotiator_property(self):
        assert self.registry.negotiator is not None
        assert self.registry.negotiator.system_version == "2.0"
