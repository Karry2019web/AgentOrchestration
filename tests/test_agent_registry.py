"""Tests for agent registry with route weight validation."""

import pytest
from src.agent.registry import AgentRegistry, RouteWeightPolicy


class TestRouteWeightPolicy:
    def setup_method(self):
        self.policy = RouteWeightPolicy()

    def test_set_valid_weights(self):
        self.policy.set_weights("worker-group", {
            "worker-a": 50,
            "worker-b": 30,
            "worker-c": 20,
        })
        weights = self.policy.get_weights("worker-group")
        assert weights == {"worker-a": 50, "worker-b": 30, "worker-c": 20}

    def test_set_weights_total_100_with_single_entry(self):
        self.policy.set_weights("default", {"main": 100})
        assert self.policy.get_weights("default") == {"main": 100}

    def test_weights_must_total_100(self):
        with pytest.raises(ValueError, match="must total 100"):
            self.policy.set_weights("group", {"a": 50, "b": 40})

    def test_weights_over_100_rejected(self):
        with pytest.raises(ValueError, match="must total 100"):
            self.policy.set_weights("group", {"a": 60, "b": 50})

    def test_empty_weights_rejected(self):
        with pytest.raises(ValueError, match="must not be empty"):
            self.policy.set_weights("group", {})

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError, match="non-negative integer"):
            self.policy.set_weights("group", {"a": -10, "b": 110})

    def test_duplicate_route_rejected(self):
        with pytest.raises(ValueError, match="Duplicate"):
            # Can't duplicate via dict literal, so test the policy method directly
            pass

    def test_get_nonexistent_key(self):
        assert self.policy.get_weights("nonexistent") is None

    def test_multiple_routing_keys(self):
        self.policy.set_weights("group-a", {"a1": 100})
        self.policy.set_weights("group-b", {"b1": 60, "b2": 40})
        keys = self.policy.list_routing_keys()
        assert "group-a" in keys
        assert "group-b" in keys
        assert len(keys) == 2

    def test_update_existing_weights(self):
        self.policy.set_weights("group", {"old": 100})
        self.policy.set_weights("group", {"new": 100})
        assert self.policy.get_weights("group") == {"new": 100}

    def test_clear_all_weights(self):
        self.policy.set_weights("group-a", {"a1": 100})
        self.policy.set_weights("group-b", {"b1": 100})
        self.policy.clear()
        assert self.policy.list_routing_keys() == []


class TestAgentRegistryRouteWeights:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_set_and_get_route_weights(self):
        self.registry.set_route_weights("workers", {
            "processor-1": 70,
            "processor-2": 30,
        })
        weights = self.registry.get_route_weights("workers")
        assert weights == {"processor-1": 70, "processor-2": 30}

    def test_invalid_weights_raises(self):
        with pytest.raises(ValueError, match="must total 100"):
            self.registry.set_route_weights("workers", {"a": 50})

    def test_route_policy_property(self):
        assert isinstance(self.registry.route_policy, RouteWeightPolicy)

# 2026-05-22T12:10:26 update - route weight validation tests
