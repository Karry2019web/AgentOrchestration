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

    def test_histogram_min_max(self):
        """Regression test: histograms should include min and max."""
        self.metrics.observe("latency", 10.0)
        self.metrics.observe("latency", 5.0)
        self.metrics.observe("latency", 20.0)
        snapshot = self.metrics.snapshot()
        hist = snapshot["histograms"]["latency"]
        assert hist["min"] == 5.0
        assert hist["max"] == 20.0
        assert hist["count"] == 3
        assert hist["sum"] == 35.0

    def test_histogram_single_value(self):
        """Single observation: min == max == the value."""
        self.metrics.observe("latency", 7.5)
        snapshot = self.metrics.snapshot()
        hist = snapshot["histograms"]["latency"]
        assert hist["min"] == 7.5
        assert hist["max"] == 7.5
