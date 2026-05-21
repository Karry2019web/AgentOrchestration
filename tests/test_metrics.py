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

    def test_histogram_max_samples(self):
        """Test that histogram storage is bounded by max_samples."""
        # Use a small max_samples for testing
        m = MetricsCollector(max_samples=10)
        for i in range(20):
            m.observe("test", float(i))
        snapshot = m.snapshot()
        # Should only keep the last 10 samples
        assert snapshot["histograms"]["test"]["count"] == 10
        # The oldest (0-9) should be dropped, newest (10-19) kept
        assert snapshot["histograms"]["test"]["sum"] == sum(range(10, 20))
        assert snapshot["histograms"]["test"]["avg"] == sum(range(10, 20)) / 10

    def test_custom_max_samples(self):
        """Test that custom max_samples is respected."""
        m = MetricsCollector(max_samples=3)
        for i in range(10):
            m.observe("latency", float(i))
        snapshot = m.snapshot()
        assert snapshot["histograms"]["latency"]["count"] == 3
        # Only last 3 values: 7, 8, 9
        assert snapshot["histograms"]["latency"]["sum"] == 7.0 + 8.0 + 9.0

    def test_default_max_samples(self):
        """Test that default max_samples is 1000."""
        m = MetricsCollector()
        for i in range(1500):
            m.observe("requests", float(i))
        snapshot = m.snapshot()
        assert snapshot["histograms"]["requests"]["count"] == 1000
        # Last 1000 values: 500-1499
        assert snapshot["histograms"]["requests"]["sum"] == sum(range(500, 1500))

    def test_histogram_below_limit(self):
        """Test that histogram works normally below the limit."""
        m = MetricsCollector(max_samples=10)
        for i in range(5):
            m.observe("test", float(i))
        snapshot = m.snapshot()
        assert snapshot["histograms"]["test"]["count"] == 5
        assert snapshot["histograms"]["test"]["sum"] == sum(range(0, 5))

# 2019-07-16T09:29:21 update

# 2019-09-09T13:35:42 update

# 2019-09-27T12:32:57 update

# 2019-10-31T18:15:44 update

# 2019-12-03T08:48:09 update

# 2019-12-12T14:59:28 update

# 2019-12-17T08:03:25 update

# 2020-03-13T11:30:29 update

# 2020-03-18T08:01:30 update

# 2020-04-15T20:08:39 update

# 2020-04-15T17:28:05 update

# 2020-10-05T20:20:34 update

# 2020-10-20T13:35:37 update

# 2020-11-13T10:55:30 update

# 2021-05-30T18:22:53 update

# 2021-06-10T12:21:04 update

# 2021-07-30T14:21:13 update

# 2021-10-12T09:49:50 update

# 2021-10-14T18:38:30 update

# 2021-11-04T15:10:57 update

# 2021-11-11T12:24:53 update

# 2022-02-01T18:07:05 update

# 2022-05-07T10:41:46 update

# 2022-08-03T13:03:09 update

# 2022-11-03T20:27:13 update

# 2023-05-27T10:00:06 update

# 2023-06-01T10:14:25 update

# 2023-06-06T19:51:40 update

# 2023-06-12T16:26:47 update

# 2023-07-17T17:02:24 update

# 2023-08-14T20:12:12 update

# 2023-10-04T09:11:52 update

# 2023-11-30T11:55:21 update

# 2023-12-07T16:49:07 update

# 2024-03-20T17:08:53 update

# 2024-07-21T20:27:36 update

# 2024-09-10T09:59:33 update

# 2024-09-17T18:56:50 update

# 2024-10-21T20:05:15 update

# 2024-10-28T15:35:37 update

# 2024-12-27T12:41:28 update

# 2025-04-04T20:26:10 update

# 2025-04-18T10:04:49 update

# 2025-05-07T18:10:13 update

# 2025-07-17T09:36:24 update

# 2025-09-10T15:28:48 update

# 2025-09-16T09:18:42 update

# 2025-12-03T18:09:40 update

# 2026-01-12T13:23:49 update

# 2026-02-17T11:42:41 update

# 2026-02-20T19:39:10 update

# 2026-03-24T19:28:19 update

# 2026-04-10T18:10:10 update
