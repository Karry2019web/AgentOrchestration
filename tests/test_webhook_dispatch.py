"""Tests for webhook per-endpoint rate limiting during fanout dispatch."""

import pytest
from src.webhook.dispatch import (
    EndpointRateLimiter,
    DispatchController,
    FanoutPolicy,
    RateLimitWindow,
)


class TestRateLimitWindow:
    def test_allows_within_limit(self):
        window = RateLimitWindow(window_seconds=60.0, max_requests=5)
        allowed, _ = window.is_allowed()
        assert allowed is True

    def test_blocks_when_exceeded(self):
        window = RateLimitWindow(window_seconds=60.0, max_requests=2)
        assert window.is_allowed()[0] is True
        assert window.is_allowed()[0] is True
        allowed, retry_after = window.is_allowed()
        assert allowed is False
        assert retry_after > 0

    def test_reset_clears_timestamps(self):
        window = RateLimitWindow(window_seconds=60.0, max_requests=2)
        window.is_allowed()
        window.is_allowed()
        assert len(window.timestamps) == 2
        window.reset()
        assert len(window.timestamps) == 0

    def test_single_request_allowed(self):
        window = RateLimitWindow(window_seconds=10.0, max_requests=1)
        assert window.is_allowed()[0] is True
        assert window.is_allowed()[0] is False


class TestEndpointRateLimiter:
    def setup_method(self):
        self.limiter = EndpointRateLimiter()

    def test_default_limit_allows(self):
        allowed, retry_after, reason = self.limiter.check("endpoint-1")
        assert allowed is True
        assert reason == "allowed"

    def test_custom_limit_blocks(self):
        self.limiter.configure(
            endpoint_id="endpoint-1", max_requests=2, window_seconds=60.0, policy=FanoutPolicy.BLOCK,
        )
        assert self.limiter.check("endpoint-1")[0] is True
        assert self.limiter.check("endpoint-1")[0] is True
        allowed, _, reason = self.limiter.check("endpoint-1")
        assert allowed is False
        assert "rate_limited_blocked" in reason

    def test_drop_policy(self):
        self.limiter.configure("endpoint-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.DROP)
        self.limiter.check("endpoint-1")
        allowed, _, reason = self.limiter.check("endpoint-1")
        assert allowed is False
        assert "dropped" in reason

    def test_bypass_policy(self):
        self.limiter.configure("endpoint-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.BYPASS)
        self.limiter.check("endpoint-1")
        allowed, _, reason = self.limiter.check("endpoint-1")
        assert allowed is True
        assert "bypass" in reason

    def test_disabled_limit_allows(self):
        self.limiter.configure("endpoint-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.BLOCK)
        self.limiter.check("endpoint-1")
        self.limiter._limits["endpoint-1"].enabled = False
        allowed, _, reason = self.limiter.check("endpoint-1")
        assert allowed is True
        assert "disabled" in reason

    def test_per_endpoint_isolation(self):
        self.limiter.configure("endpoint-a", max_requests=1, window_seconds=60.0)
        self.limiter.configure("endpoint-b", max_requests=5, window_seconds=60.0)
        self.limiter.check("endpoint-a")
        self.limiter.check("endpoint-b")
        self.limiter.check("endpoint-b")
        allowed, _, _ = self.limiter.check("endpoint-a")
        assert allowed is False
        for _ in range(3):
            allowed, _, _ = self.limiter.check("endpoint-b")
            assert allowed is True

    def test_remove_endpoint(self):
        self.limiter.configure("ep-1", max_requests=1, window_seconds=60.0)
        self.limiter.remove("ep-1")
        assert self.limiter.check("ep-1")[0] is True

    def test_reset_all(self):
        self.limiter.configure("ep-1", max_requests=1, window_seconds=60.0)
        self.limiter.check("ep-1")
        self.limiter.reset_all()
        allowed, _, _ = self.limiter.check("ep-1")
        assert allowed is True

    def test_stats(self):
        self.limiter.configure("ep-1", max_requests=10, window_seconds=60.0)
        self.limiter.check("ep-1")
        self.limiter.check("ep-1")
        stats = self.limiter.stats("ep-1")
        assert stats["endpoint_id"] == "ep-1"
        assert stats["current_count"] == 2
        assert stats["remaining"] == 8


class TestDispatchController:
    def setup_method(self):
        self.controller = DispatchController()

    def test_single_dispatch_allowed(self):
        result = self.controller.dispatch("evt-1", "endpoint-1")
        assert result["status"] == "dispatched"
        assert result["event_id"] == "evt-1"
        assert result["endpoint_id"] == "endpoint-1"

    def test_single_dispatch_rejected(self):
        self.controller.rate_limiter.configure("endpoint-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.BLOCK)
        self.controller.dispatch("evt-1", "endpoint-1")
        result = self.controller.dispatch("evt-2", "endpoint-1")
        assert result["status"] == "rejected"
        assert "retry_after_seconds" in result

    def test_fanout_multiple_endpoints(self):
        self.controller.rate_limiter.configure("ep-a", max_requests=1, window_seconds=60.0)
        self.controller.rate_limiter.configure("ep-b", max_requests=5, window_seconds=60.0)
        self.controller.rate_limiter.configure("ep-c", max_requests=1, window_seconds=60.0)
        results = self.controller.fanout("evt-1", ["ep-a", "ep-b", "ep-c"])
        assert len(results) == 3
        assert all(r["status"] == "dispatched" for r in results)
        results2 = self.controller.fanout("evt-2", ["ep-a", "ep-b", "ep-c"])
        assert results2[0]["status"] == "rejected"
        assert results2[1]["status"] == "dispatched"
        assert results2[2]["status"] == "rejected"

    def test_retry_respects_rate_limit(self):
        self.controller.rate_limiter.configure("ep-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.BLOCK)
        r1 = self.controller.dispatch("evt-1", "ep-1")
        assert r1["status"] == "dispatched"
        r2 = self.controller.retry("evt-1", "ep-1", attempt=2)
        assert r2["status"] == "rejected"
        assert r2.get("idempotent") is True
        assert r2.get("attempt") == 2

    def test_workspace_isolation(self):
        r1 = self.controller.dispatch("evt-1", "ep-1", workspace_id="workspace-a")
        assert r1["workspace_id"] == "workspace-a"
        results = self.controller.fanout("evt-2", ["ep-1", "ep-2"], workspace_id="workspace-b")
        for r in results:
            assert r["workspace_id"] == "workspace-b"

    def test_reset_stats(self):
        self.controller.dispatch("evt-1", "ep-1")
        self.controller.dispatch("evt-2", "ep-1")
        self.controller.reset_stats()
        stats = self.controller.get_stats("ep-1")
        assert stats["total_dispatched"] == 0
        assert stats["total_rejected"] == 0

    def test_fanout_no_endpoints(self):
        results = self.controller.fanout("evt-1", [])
        assert results == []

    def test_rejection_counts(self):
        self.controller.rate_limiter.configure("ep-1", max_requests=1, window_seconds=60.0, policy=FanoutPolicy.BLOCK)
        self.controller.dispatch("evt-1", "ep-1")
        self.controller.dispatch("evt-2", "ep-1")
        self.controller.dispatch("evt-3", "ep-1")
        stats = self.controller.get_stats("ep-1")
        assert stats["total_dispatched"] == 1
        assert stats["total_rejected"] == 2

# 2026-05-23T06:30:00 update
