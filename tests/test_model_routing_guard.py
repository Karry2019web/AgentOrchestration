"""Tests for ModelRoutingGuard in the agent runtime."""

import pytest
from src.agent.model_routing_guard import (
    ModelRoutingGuard,
    ModelMode,
    RoutingDecision,
    SUPPORTED_MODES,
    UNSUPPORTED_FALLBACK_MODES,
)


class TestModelRoutingGuard:
    def setup_method(self):
        self.guard = ModelRoutingGuard(max_retries=3)

    def test_supported_mode_allowed(self):
        """Chat mode should be allowed for routing fallback."""
        decision = self.guard.check_fallback("route-1", ModelMode.CHAT)
        assert decision.allowed is True
        assert "supported" in decision.reason.lower()

    def test_unsupported_mode_blocked(self):
        """IMAGE mode should be blocked from routing fallback."""
        decision = self.guard.check_fallback("route-2", ModelMode.IMAGE)
        assert decision.allowed is False
        assert "not supported" in decision.reason.lower()

    def test_audio_mode_blocked(self):
        """AUDIO mode should be blocked from routing fallback."""
        decision = self.guard.check_fallback("route-3", ModelMode.AUDIO)
        assert decision.allowed is False
        assert "not supported" in decision.reason.lower()

    def test_fallback_chain_with_unsupported_mode(self):
        """Fallback chain containing unsupported modes should be blocked."""
        decision = self.guard.check_fallback(
            "route-4", ModelMode.CHAT,
            fallback_chain=[ModelMode.CHAT, ModelMode.IMAGE]
        )
        assert decision.allowed is False
        assert "unsupported" in decision.reason.lower()

    def test_fallback_chain_all_supported(self):
        """Fallback chain with all supported modes should be allowed."""
        decision = self.guard.check_fallback(
            "route-5", ModelMode.CHAT,
            fallback_chain=[ModelMode.CHAT, ModelMode.COMPLETION]
        )
        assert decision.allowed is True

    def test_completion_mode_allowed(self):
        """COMPLETION mode should be allowed for routing fallback."""
        decision = self.guard.check_fallback("route-6", ModelMode.COMPLETION)
        assert decision.allowed is True

    def test_embedding_mode_allowed(self):
        """EMBEDDING mode should be allowed for routing fallback."""
        decision = self.guard.check_fallback("route-7", ModelMode.EMBEDDING)
        assert decision.allowed is True

    def test_tool_call_mode_allowed(self):
        """TOOL_CALL mode should be allowed for routing fallback."""
        decision = self.guard.check_fallback("route-8", ModelMode.TOOL_CALL)
        assert decision.allowed is True

    def test_streaming_mode_allowed(self):
        """STREAMING mode should be allowed for routing fallback."""
        decision = self.guard.check_fallback("route-9", ModelMode.STREAMING)
        assert decision.allowed is True

    def test_decision_is_persisted(self):
        """Decisions should be persisted before returning."""
        _ = self.guard.check_fallback("route-10", ModelMode.CHAT)
        decisions = self.guard.get_decisions("route-10")
        assert len(decisions) == 1
        assert decisions[0].allowed is True

    def test_record_routing_bounded_retries(self):
        """Record routing should respect max_retries."""
        route_id = "route-11"
        for i in range(1, 4):
            result = self.guard.record_routing(route_id, ModelMode.CHAT, attempt=i)
            assert result is True, f"Attempt {i} should succeed"

        result = self.guard.record_routing(route_id, ModelMode.CHAT, attempt=4)
        assert result is False, "Attempt 4 should exceed max_retries"

    def test_record_routing_idempotent(self):
        """Same attempt number should be idempotent."""
        route_id = "route-12"
        self.guard.record_routing(route_id, ModelMode.CHAT, attempt=2)
        result = self.guard.record_routing(route_id, ModelMode.CHAT, attempt=2)
        assert result is True

    def test_mark_terminal(self):
        """Terminal routes should reject further attempts."""
        route_id = "route-13"
        self.guard.record_routing(route_id, ModelMode.CHAT, attempt=1)
        self.guard.mark_terminal(route_id)
        result = self.guard.record_routing(route_id, ModelMode.CHAT, attempt=2)
        assert result is False

    def test_get_routing_state(self):
        """Routing state should be queryable."""
        route_id = "route-14"
        self.guard.record_routing(route_id, ModelMode.CHAT, attempt=1)
        state = self.guard.get_routing_state(route_id)
        assert state is not None
        assert state["resolved_mode"] == "chat"
        assert state["terminal"] is False

    def test_decision_to_dict(self):
        """RoutingDecision.to_dict() should return serializable dict."""
        decision = RoutingDecision(ModelMode.CHAT, True, "test reason", 1000.0)
        d = decision.to_dict()
        assert d["mode"] == "chat"
        assert d["allowed"] is True
        assert d["reason"] == "test reason"
        assert d["timestamp"] == 1000.0

    def test_runtime_route_to_model(self):
        """AgentRuntime.route_to_model should use ModelRoutingGuard."""
        from src.agent.runtime import AgentRuntime
        runtime = AgentRuntime()
        result = runtime.route_to_model("test-agent", "chat")
        assert result is True, "Chat routing should succeed"

        result = runtime.route_to_model("test-agent", "image")
        assert result is False, "Image routing should fail"

        result = runtime.route_to_model("test-agent", "audio")
        assert result is False, "Audio routing should fail"

    def test_unsupported_modes_enum(self):
        """Verify UNSUPPORTED_FALLBACK_MODES contains expected modes."""
        assert ModelMode.IMAGE in UNSUPPORTED_FALLBACK_MODES
        assert ModelMode.AUDIO in UNSUPPORTED_FALLBACK_MODES
        assert ModelMode.CHAT not in UNSUPPORTED_FALLBACK_MODES
        assert ModelMode.COMPLETION not in UNSUPPORTED_FALLBACK_MODES
