"""Tests for SchemaCache and capability-contract-aware caching."""

import pytest
from src.agent.schema_cache import (
    SchemaCache,
    ContractVersionError,
    CachedSchema,
    validate_contract_change,
    _parse_version,
)


class TestSchemaCache:
    def setup_method(self):
        self.cache = SchemaCache()

    def test_set_and_get(self):
        contract = {"name": "transform", "version": "1.0.0"}
        schema = {"input": "bytes", "output": "bytes"}
        self.cache.set("handler.transform", schema, contract)
        entry = self.cache.get("handler.transform", contract)
        assert entry is not None
        assert entry.schema == schema

    def test_get_missing_key(self):
        assert self.cache.get("nonexistent") is None

    def test_get_stale_contract_eviction(self):
        old_contract = {"name": "transform", "version": "1.0.0"}
        new_contract = {"name": "transform", "version": "2.0.0"}
        self.cache.set("handler.transform", {"old": True}, old_contract)
        # Get with new contract - should evict and return None
        assert self.cache.get("handler.transform", new_contract) is None

    def test_invalidate_contract(self):
        contract = {"name": "transform", "version": "1.0.0"}
        self.cache.set("handler.a", {"a": 1}, contract)
        self.cache.set("handler.b", {"b": 2}, contract)
        assert self.cache.size == 2
        count = self.cache.invalidate_contract(contract)
        assert count == 2
        assert self.cache.size == 0

    def test_invalidate_contract_partial(self):
        c1 = {"name": "transform", "version": "1.0.0"}
        c2 = {"name": "monitor", "version": "1.0.0"}
        self.cache.set("handler.a", {"a": 1}, c1)
        self.cache.set("handler.b", {"b": 2}, c2)
        count = self.cache.invalidate_contract(c1)
        assert count == 1
        assert self.cache.size == 1
        assert self.cache.get("handler.b", c2) is not None

    def test_invalidate_key(self):
        contract = {"name": "transform", "version": "1.0.0"}
        self.cache.set("handler.x", {"x": 1}, contract)
        assert self.cache.invalidate_key("handler.x") is True
        assert self.cache.get("handler.x", contract) is None

    def test_invalidate_nonexistent_key(self):
        assert self.cache.invalidate_key("nothing") is False

    def test_clear(self):
        c1 = {"name": "a", "version": "1.0.0"}
        c2 = {"name": "b", "version": "1.0.0"}
        self.cache.set("k1", {}, c1)
        self.cache.set("k2", {}, c2)
        self.cache.clear()
        assert self.cache.size == 0

    def test_accessed_count_increments(self):
        contract = {"name": "t", "version": "1.0.0"}
        self.cache.set("k", {}, contract)
        self.cache.get("k", contract)
        self.cache.get("k", contract)
        assert self.cache._entries["k"].accessed_count == 2

    def test_set_replaces_old_contract(self):
        old = {"name": "t", "version": "1.0.0"}
        new = {"name": "t", "version": "2.0.0"}
        self.cache.set("k", {"old": True}, old)
        self.cache.set("k", {"new": True}, new)
        entry = self.cache.get("k", new)
        assert entry is not None
        assert entry.schema == {"new": True}


class TestValidateContractChange:
    def test_first_registration_valid(self):
        # Old contract is None - always valid
        validate_contract_change(None, {"name": "t", "version": "1.0.0"})

    def test_name_change_raises(self):
        old = {"name": "transform", "version": "1.0.0"}
        new = {"name": "monitor", "version": "1.0.0"}
        with pytest.raises(ContractVersionError, match="identity change"):
            validate_contract_change(old, new)

    def test_version_downgrade_raises(self):
        old = {"name": "t", "version": "2.0.0"}
        new = {"name": "t", "version": "1.0.0"}
        with pytest.raises(ContractVersionError, match="downgrade"):
            validate_contract_change(old, new)

    def test_required_fields_removed_raises(self):
        old = {"name": "t", "version": "1.0.0", "required": ["input", "output"]}
        new = {"name": "t", "version": "1.0.0", "required": ["input"]}
        with pytest.raises(ContractVersionError, match="required fields"):
            validate_contract_change(old, new)

    def test_compatible_change_allowed(self):
        old = {"name": "t", "version": "1.0.0", "required": ["input"]}
        new = {"name": "t", "version": "1.1.0", "required": ["input", "output"]}
        # Should not raise
        validate_contract_change(old, new)

    def test_patch_bump_allowed(self):
        old = {"name": "t", "version": "1.0.0"}
        new = {"name": "t", "version": "1.0.1"}
        validate_contract_change(old, new)


class TestAgentRegistrySchemaIntegration:
    """Integration tests: AgentRegistry + SchemaCache work together."""

    def test_register_caches_schema(self):
        from src.agent.registry import AgentRegistry
        reg = AgentRegistry()
        agent_id = reg.register("worker-1", "worker.processor")
        schema = reg.get_schema(agent_id)
        assert schema is not None
        assert schema["type"] == "worker.processor"

    def test_contract_change_invalidates_schema(self):
        from src.agent.registry import AgentRegistry
        reg = AgentRegistry()
        agent_id = reg.register("worker-1", "worker.processor")
        # Schema is cached
        schema_before = reg.get_schema(agent_id)
        assert schema_before is not None

        # Update contract (same name, version bump) - should succeed
        new_contract = {"name": "worker.processor", "version": "2.0.0", "required": []}
        reg.update_capability_contract(agent_id, new_contract)

        # Schema should reflect the new contract
        schema_after = reg.get_schema(agent_id)
        assert schema_after is not None
        assert schema_after["contract"]["version"] == "2.0.0"

    def test_stale_contract_returns_none(self):
        from src.agent.registry import AgentRegistry
        reg = AgentRegistry()
        agent_id = reg.register("worker-1", "worker.processor")

        # Bypass update method and directly change contract to simulate drift
        old_contract = reg._capability_contracts[agent_id]
        new_contract = {"name": "worker.processor", "version": "3.0.0", "required": []}

        # Invalidate old contract (simulating external change)
        reg._schema_cache.invalidate_contract(old_contract)

        # get_schema should return None (schema evicted)
        assert reg.get_schema(agent_id) is None

        # Until we set a new one via update
        reg.update_capability_contract(agent_id, new_contract)
        assert reg.get_schema(agent_id) is not None
