"""Tests for the canary analysis module."""

import pytest
import time
from src.orchestrator.canary import CanaryAnalyzer, CanaryDecision
from src.orchestrator.scheduler import TaskScheduler


class TestCanaryAnalyzer:
    def test_analyze_passes_when_metrics_healthy(self):
        analyzer = CanaryAnalyzer()
        decision = analyzer.analyze(
            queue_depths={"default": 5},
            processing_latencies={"default": 2.0},
            in_flight_count=3,
            worker_count=10,
        )
        assert decision.passed is True
        assert len(decision.reasons) > 0

    def test_analyze_fails_on_backlog_exceeded(self):
        analyzer = CanaryAnalyzer(backlog_threshold=10)
        decision = analyzer.analyze(
            queue_depths={"default": 100},
            processing_latencies={"default": 1.0},
            in_flight_count=3,
            worker_count=10,
        )
        assert decision.passed is False
        assert any("backlog" in r.lower() for r in decision.reasons)

    def test_analyze_fails_on_high_latency(self):
        analyzer = CanaryAnalyzer(latency_threshold=10.0)
        decision = analyzer.analyze(
            queue_depths={"default": 5},
            processing_latencies={"default": 60.0},
            in_flight_count=3,
            worker_count=10,
        )
        assert decision.passed is False
        assert any("latency" in r.lower() for r in decision.reasons)

    def test_analyze_fails_on_lease_renewal_failures(self):
        analyzer = CanaryAnalyzer(lease_failure_rate_threshold=0.05)
        analyzer.record_lease_renewal(success=True)
        analyzer.record_lease_renewal(success=False)
        analyzer.record_lease_renewal(success=False)

        decision = analyzer.analyze(
            queue_depths={"default": 5},
            processing_latencies={"default": 1.0},
            in_flight_count=3,
            worker_count=10,
        )
        assert decision.passed is False
        assert any("lease" in r.lower() for r in decision.reasons)

    def test_analyze_fails_on_worker_saturation(self):
        analyzer = CanaryAnalyzer()
        decision = analyzer.analyze(
            queue_depths={"default": 5},
            processing_latencies={"default": 1.0},
            in_flight_count=10,
            worker_count=5,
        )
        assert decision.passed is False
        assert any("capacity" in r.lower() for r in decision.reasons)

    def test_reset_metrics(self):
        analyzer = CanaryAnalyzer()
        analyzer.record_lease_renewal(success=False)
        analyzer.record_lease_renewal(success=False)
        analyzer.reset_metrics()

        decision = analyzer.analyze(
            queue_depths={"default": 5},
            processing_latencies={"default": 1.0},
            in_flight_count=3,
            worker_count=10,
        )
        assert decision.passed is True


class TestTaskSchedulerMetrics:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_queue_depth(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"}, queue="high")
        self.scheduler.enqueue({"type": "c"}, queue="high")

        depths = self.scheduler.get_queue_depth()
        assert depths.get("default") == 1
        assert depths.get("high") == 2

    def test_total_backlog(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        self.scheduler.enqueue({"type": "c"}, queue="high")

        assert self.scheduler.get_total_backlog() == 3

    def test_in_flight_count(self):
        import asyncio

        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.get_in_flight_count() == 1

        self.scheduler.complete(task["id"])
        assert self.scheduler.get_in_flight_count() == 0

    def test_average_latency(self):
        import asyncio

        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        # Simulate processing time
        self.scheduler.complete(task["id"])

        latencies = self.scheduler.get_average_latency()
        assert "default" in latencies
        assert latencies["default"] >= 0

    def test_lease_renewal_metrics(self):
        self.scheduler.record_lease_renewal(success=True)
        self.scheduler.record_lease_renewal(success=True)
        self.scheduler.record_lease_renewal(success=False)

        attempts, failures = self.scheduler.get_lease_renewal_metrics()
        assert attempts == 3
        assert failures == 1

    def test_metrics_snapshot(self):
        self.scheduler.enqueue({"type": "test"}, queue="default")
        snapshot = self.scheduler.get_metrics_snapshot()
        assert "queue_depth" in snapshot
        assert "total_backlog" in snapshot
        assert "in_flight" in snapshot
        assert "average_latency" in snapshot
        assert "lease_renewal_attempts" in snapshot
        assert "lease_renewal_failures" in snapshot
