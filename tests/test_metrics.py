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

    def test_increment_no_max_counter(self):
        """Default behavior: no clamping, unbounded growth."""
        m = MetricsCollector()
        for _ in range(1000):
            m.increment("unbounded.counter")
        snap = m.snapshot()
        assert snap["counters"]["unbounded.counter"] == 1000

    def test_increment_with_max_counter_clamps(self):
        """Counter clamps at max_counter when set."""
        m = MetricsCollector(max_counter=10)
        for _ in range(100):
            m.increment("clamped.counter")
        snap = m.snapshot()
        assert snap["counters"]["clamped.counter"] == 10

    def test_increment_max_counter_zero(self):
        """max_counter=0 prevents any positive value."""
        m = MetricsCollector(max_counter=0)
        m.increment("zero.counter", 5)
        snap = m.snapshot()
        assert snap["counters"]["zero.counter"] == 0

    def test_increment_max_counter_isolation(self):
        """Different metrics with max_counter set independently."""
        m = MetricsCollector(max_counter=50)
        m.increment("a", 30)
        m.increment("b", 30)
        snap = m.snapshot()
        assert snap["counters"]["a"] == 30
        assert snap["counters"]["b"] == 30

    def test_increment_max_counter_with_existing_value(self):
        """Existing counter value above max_counter gets clamped on next increment."""
        m = MetricsCollector(max_counter=5)
        m.increment("counter", 10)
        snap = m.snapshot()
        assert snap["counters"]["counter"] == 5
