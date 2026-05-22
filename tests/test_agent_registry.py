"""Tests for agent registry with protocol negotiation."""

import pytest
from src.agent.registry import (
    AgentRegistry,
    AgentStatus,
    ProtocolVersion,
    CURRENT_PROTOCOL,
    MINIMUM_PROTOCOL,
)


class TestProtocolVersion:
    def test_parse_full(self):
        v = ProtocolVersion.parse("2.1.0")
        assert v.major == 2
        assert v.minor == 1
        assert v.patch == 0

    def test_parse_partial(self):
        v = ProtocolVersion.parse("2.1")
        assert v.major == 2
        assert v.minor == 1
        assert v.patch == 0

    def test_parse_single(self):
        v = ProtocolVersion.parse("2")
        assert v.major == 2
        assert v.minor == 0
        assert v.patch == 0

    def test_compatible_same_major_higher_minor(self):
        v1 = ProtocolVersion(2, 2, 0)
        v2 = ProtocolVersion(2, 1, 0)
        assert v1.is_compatible_with(v2)

    def test_incompatible_different_major(self):
        v1 = ProtocolVersion(3, 0, 0)
        v2 = ProtocolVersion(2, 0, 0)
        assert not v1.is_compatible_with(v2)

    def test_incompatible_lower_minor(self):
        v1 = ProtocolVersion(2, 0, 0)
        v2 = ProtocolVersion(2, 1, 0)
        assert not v1.is_compatible_with(v2)

    def test_exact_match(self):
        v1 = ProtocolVersion(2, 1, 0)
        v2 = ProtocolVersion(2, 1, 0)
        assert v1.is_compatible_with(v2)

    def test_str_representation(self):
        v = ProtocolVersion(2, 1, 3)
        assert str(v) == "2.1.3"


class TestAgentRegistryProtocol:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_with_valid_protocol(self):
        agent_id = self.registry.register("test-agent", "worker.processor", protocol_version="2.1.0")
        assert agent_id is not None
        assert self.registry.count() == 1
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == "2.1.0"

    def test_register_without_protocol_falls_back_to_current(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == str(CURRENT_PROTOCOL)

    def test_register_with_incompatible_major_version(self):
        with pytest.raises(ValueError, match="major version mismatch"):
            self.registry.register("test-agent", "worker.processor", protocol_version="3.0.0")

    def test_register_with_too_old_version(self):
        with pytest.raises(ValueError, match="Incompatible"):
            self.registry.register("test-agent", "worker.processor", protocol_version="1.9.0")

    def test_register_with_invalid_format(self):
        with pytest.raises(ValueError, match="invalid protocol version"):
            self.registry.register("test-agent", "worker.processor", protocol_version="abc")

    def test_register_with_none_protocol(self):
        with pytest.raises(ValueError, match="Protocol version is required"):
            self.registry.register("test-agent", "worker.processor", protocol_version=None)

    def test_resolve_compatible_agent(self):
        agent_id = self.registry.register("test-agent", "worker.processor", protocol_version="2.1.0")
        resolved = self.registry.resolve(agent_id)
        assert resolved is not None
        assert resolved["id"] == agent_id

    def test_resolve_nonexistent_agent(self):
        resolved = self.registry.resolve("nonexistent")
        assert resolved is None

    def test_resolve_incompatible_agent_fails_and_marks_failed(self):
        # Register with a valid version first
        agent_id = self.registry.register("test-agent", "worker.processor", protocol_version="2.1.0")
        # Manially set an incompatible version to simulate protocol change
        agent = self.registry.get(agent_id)
        agent["protocol_version"] = "1.0.0"
        # Resolution should fail
        resolved = self.registry.resolve(agent_id)
        assert resolved is None
        # Agent should be marked as FAILED
        failed_agent = self.registry.get(agent_id)
        assert failed_agent["status"] == "failed"

    def test_cache_invalidation_on_registration(self):
        v1 = self.registry.get_cache_version()
        self.registry.register("agent-1", "worker.processor", protocol_version="2.1.0")
        v2 = self.registry.get_cache_version()
        assert v2 > v1

    def test_cache_invalidation_on_delete(self):
        agent_id = self.registry.register("agent-1", "worker.processor", protocol_version="2.1.0")
        v1 = self.registry.get_cache_version()
        self.registry.delete(agent_id)
        v2 = self.registry.get_cache_version()
        assert v2 > v1

    def test_negotiated_protocol_tracking(self):
        agent_id = self.registry.register("agent-a", "worker.processor", protocol_version="2.1.0")
        negotiated = self.registry.get_negotiated_protocol(agent_id)
        assert negotiated == "2.1.0"

    def test_negotiated_protocol_updated_on_resolve(self):
        agent_id = self.registry.register("agent-a", "worker.processor", protocol_version="2.2.0")
        self.registry.resolve(agent_id)
        negotiated = self.registry.get_negotiated_protocol(agent_id)
        assert negotiated == "2.2.0"

    def test_negotiated_protocol_removed_on_delete(self):
        agent_id = self.registry.register("agent-a", "worker.processor", protocol_version="2.1.0")
        self.registry.delete(agent_id)
        assert self.registry.get_negotiated_protocol(agent_id) is None

    def test_existing_register_without_protocol_still_works(self):
        """Backward compatibility: old registration calls without protocol_version still work."""
        agent_id = self.registry.register("legacy-agent", "monitor.watcher")
        assert agent_id is not None
        agent = self.registry.get(agent_id)
        assert agent["protocol_version"] == str(CURRENT_PROTOCOL)

    def test_resolve_clears_cache_on_failure(self):
        agent_id = self.registry.register("agent-a", "worker.processor", protocol_version="2.1.0")
        v1 = self.registry.get_cache_version()
        # Force incompatible protocol
        agent = self.registry.get(agent_id)
        agent["protocol_version"] = "0.5.0"
        self.registry.resolve(agent_id)
        v2 = self.registry.get_cache_version()
        assert v2 > v1

# 2026-05-22T12:10:26 update - protocol negotiation tests
