import pytest
from src.common.metrics import MetricsCollector


class TestMetricsCollector:
    def setup_method(self):
        self.metrics = MetricsCollector()

    def test_reset_clears_counters(self):
        self.metrics.increment("requests.total")
        self.metrics.increment("errors")
        snapshot_before = self.metrics.snapshot()
        assert snapshot_before["counters"]["requests.total"] == 1
        assert snapshot_before["counters"]["errors"] == 1
        self.metrics.reset()
        snapshot_after = self.metrics.snapshot()
        assert snapshot_after["counters"] == {}

    def test_reset_clears_gauges(self):
        self.metrics.gauge("memory.usage", 85.5)
        self.metrics.reset()
        snapshot = self.metrics.snapshot()
        assert snapshot["gauges"] == {}

    def test_reset_clears_histograms(self):
        self.metrics.observe("response.time", 0.5)
        self.metrics.observe("response.time", 1.5)
        self.metrics.reset()
        snapshot = self.metrics.snapshot()
        assert snapshot["histograms"] == {}

    def test_reset_clears_timers(self):
        self.metrics.start_timer("operation")
        import time
        time.sleep(0.01)
        duration = self.metrics.stop_timer("operation")
        assert duration > 0.005
        self.metrics.gauge("after.timer", 1.0)
        self.metrics.reset()
        snapshot = self.metrics.snapshot()
        assert snapshot["gauges"] == {}

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
