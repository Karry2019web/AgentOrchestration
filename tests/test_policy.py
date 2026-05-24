"""Tests for the policy engine and fail-closed behavior."""

import time
import pytest
from src.common.policy import PolicyEngine, PolicyDecision


class TestPolicyEngine:
    def test_default_allow_when_no_endpoint(self):
        """Without an endpoint configured, the engine allows everything."""
        engine = PolicyEngine()
        assert engine.is_available() is True
        decision = engine.evaluate("task.execute", "agent:test-1")
        assert decision == PolicyDecision.ALLOW

    def test_fail_closed_when_unavailable(self):
        """When the engine is unavailable, operations are denied."""
        engine = PolicyEngine(endpoint="http://localhost:1", timeout=0.1)
        # Force unhealthy state
        engine._healthy = False
        engine._last_health_check = time.time()
        assert engine.is_available() is False
        decision = engine.evaluate("task.execute", "agent:test-1")
        assert decision == PolicyDecision.DENY

    def test_is_available_caching(self):
        """Health check results are cached within the check interval."""
        engine = PolicyEngine()
        engine._last_health_check = time.time()
        engine._healthy = True
        # Should use cached value, not make a real call
        assert engine.is_available() is True

    def test_is_available_cached_unhealthy(self):
        """Unhealthy state is also cached."""
        engine = PolicyEngine()
        engine._last_health_check = time.time()
        engine._healthy = False
        assert engine.is_available() is False

    def test_policy_decision_enum_values(self):
        assert PolicyDecision.ALLOW.value == "allow"
        assert PolicyDecision.DENY.value == "deny"
        assert PolicyDecision.ERROR.value == "error"


class TestPolicyIntegration:
    """Test policy integration in the orchestration engine."""

    def test_engine_accepts_policy(self):
        from src.orchestrator.engine import OrchestrationEngine
        engine = PolicyEngine()
        orch = OrchestrationEngine(policy_engine=engine)
        assert orch.policy is engine

    def test_engine_default_policy(self):
        from src.orchestrator.engine import OrchestrationEngine
        orch = OrchestrationEngine()
        assert orch.policy is not None
        assert orch.policy.is_available() is True

# 2026-05-24T05:58:00 update
