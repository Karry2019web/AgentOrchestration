import pytest
from src.common.metrics import MetricsCollector


class TestMetricsCollector:
    def setup_method(self):
        self.metrics = MetricsCollector()

    def test_increment(self):
        self.metrics.increment("requests.total")
        self.metrics.increment("requests.total")
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"]["requests.total"] == 2

    def test_gauge(self):
        self.metrics.gauge("memory.usage", 85.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["gauges"]["memory.usage"] == 85.5

    def test_observe(self):
        self.metrics.observe("response.time", 0.5)
        self.metrics.observe("response.time", 1.5)
        snapshot = self.metrics.snapshot()
        assert snapshot["histograms"]["response.time"]["count"] == 2
        assert snapshot["histograms"]["response.time"]["avg"] == 1.0

    def test_timer(self):
        self.metrics.start_timer("operation")
        import time
        time.sleep(0.01)
        duration = self.metrics.stop_timer("operation")
        assert duration > 0.005

    def test_reset_clears_all(self):
        self.metrics.increment("requests.total", 5)
        self.metrics.gauge("memory.usage", 85.5)
        self.metrics.observe("response.time", 0.5)
        self.metrics.start_timer("operation")
        self.metrics.stop_timer("operation")
        self.metrics.reset()
        snapshot = self.metrics.snapshot()
        assert snapshot["counters"] == {}
        assert snapshot["gauges"] == {}
        assert snapshot["histograms"] == {}

    def test_reset_allows_new_metrics(self):
        self.metrics.increment("old", 1)
        self.metrics.reset()
        self.metrics.increment("new", 3)
        snapshot = self.metrics.snapshot()
        assert "old" not in snapshot["counters"]
        assert snapshot["counters"]["new"] == 3

    def test_reset_clears_active_timers(self):
        self.metrics.start_timer("active")
        self.metrics.reset()
        duration = self.metrics.stop_timer("active")
        assert duration == 0.0
