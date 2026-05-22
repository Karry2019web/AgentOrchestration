"""Tests for counter increment validation."""

import pytest
from src.common.metrics import MetricsCollector


class TestCounterIntegrity:
    """Tests that counters reject negative increments."""

    def setup_method(self):
        self.metrics = MetricsCollector()

    def test_increment_positive(self):
        self.metrics.increment("requests.total", 5)
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 5

    def test_increment_default(self):
        self.metrics.increment("requests.total")
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 1

    def test_rejects_negative_increment(self):
        with pytest.raises(ValueError, match="negative value"):
            self.metrics.increment("requests.total", -1)

    def test_rejects_negative_default_zero(self):
        with pytest.raises(ValueError, match="negative value"):
            self.metrics.increment("requests.total", -5)

    def test_zero_should_work(self):
        self.metrics.increment("requests.total", 0)
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 0
