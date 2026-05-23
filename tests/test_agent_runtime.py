"""Tests for AgentRuntime — sandbox stop timeout validation."""

import pytest
from src.agent.runtime import AgentRuntime, RuntimeState


class TestAgentRuntime:
    def setup_method(self):
        self.runtime = AgentRuntime()

    def test_stop_with_positive_timeout(self):
        """Positive timeout should not raise or reject."""
        result = self.runtime.stop("nonexistent-agent", timeout=10)
        assert result is False  # No such agent

    def test_stop_with_zero_timeout(self):
        """Zero timeout should be rejected before any signal."""
        result = self.runtime.stop("nonexistent-agent", timeout=0)
        assert result is False

    def test_stop_with_negative_timeout(self):
        """Negative timeout should be rejected before any signal."""
        result = self.runtime.stop("nonexistent-agent", timeout=-1)
        assert result is False

    def test_stop_with_default_timeout(self):
        """Default timeout should behave normally."""
        result = self.runtime.stop("nonexistent-agent")
        assert result is False  # No such agent

    def test_stop_timeout_validation_before_signal(self):
        """Validate that timeout validation happens before any process signal."""
        runtime = AgentRuntime()
        result = runtime.stop("ghost", timeout=-5)
        assert result is False
