"""Tests for canary analysis — queue backlog, processing latency, lease renewal."""

import time
from src.orchestrator.scheduler import SchedulerMetrics, TaskScheduler
from src.orchestrator.canary import CanaryAnalyzer, CanaryThresholds, CanaryDecision


class TestSchedulerMetrics:
    def setup_method(self):
        self.metrics = SchedulerMetrics()

    def test_initial_state(self):
        assert self.metrics.avg_processing_time == 0.0
        assert self.metrics.p99_processing_time == 0.0
        assert self.metrics.backlog_peak == 0
        assert self.metrics.lease_renewal_count == 0
        assert self.metrics.lease_failure_count == 0
        assert self.metrics.health_score == 1.0

    def test_processing_time_records(self):
        self.metrics.record_processing_time(1.0)
        self.metrics.record_processing_time(3.0)
        assert self.metrics.avg_processing_time == 2.0
        assert 2.9 < self.metrics.p99_processing_time <= 3.0

    def test_lease_tracking(self):
        self.metrics.record_lease_renewal()
        self.metrics.record_lease_renewal()
        self.metrics.record_lease_failure()
        assert self.metrics.lease_renewal_count == 2
        assert self.metrics.lease_failure_count == 1

    def test_backlog_peak(self):
        self.metrics.observe_backlog(5)
        self.metrics.observe_backlog(20)
        self.metrics.observe_backlog(10)
        assert self.metrics.backlog_peak == 20

    def test_health_score_perfect(self):
        self.metrics.record_lease_renewal()
        self.metrics.record_processing_time(1.0)
        assert self.metrics.health_score == 1.0

    def test_health_score_lease_failure_penalty(self):
        self.metrics.record_lease_renewal()
        self.metrics.record_lease_failure()
        score = self.metrics.health_score
        assert 0.0 < score < 1.0

    def test_health_score_high_latency_penalty(self):
        self.metrics.record_processing_time(60.0)
        score = self.metrics.health_score
        assert score < 0.8

    def test_health_score_high_backlog_penalty(self):
        self.metrics.observe_backlog(500)
        score = self.metrics.health_score
        assert score < 0.9

    def test_health_score_minimum_floor(self):
        self.metrics.record_lease_failure()
        self.metrics.record_processing_time(300.0)
        self.metrics.observe_backlog(5000)
        assert self.metrics.health_score >= 0.0


class TestCanaryAnalyzer:
    def setup_method(self):
        self.analyzer = CanaryAnalyzer()

    def test_promote_healthy_worker(self):
        metrics = SchedulerMetrics()
        metrics.record_lease_renewal()
        metrics.record_lease_renewal()
        metrics.record_lease_renewal()
        metrics.record_processing_time(2.0)
        metrics.record_processing_time(1.5)

        decision = self.analyzer.analyze(metrics, backlog_depth=5)
        assert decision.can_promote
        assert decision.reason == "All checks passed"

    def test_rollback_high_backlog(self):
        metrics = SchedulerMetrics()
        decision = self.analyzer.analyze(metrics, backlog_depth=200)
        assert not decision.can_promote
        assert "Backlog" in decision.reason
        assert decision.backlog_depth == 200

    def test_rollback_high_latency(self):
        metrics = SchedulerMetrics()
        metrics.record_processing_time(60.0)
        decision = self.analyzer.analyze(metrics)
        assert not decision.can_promote
        assert "latency" in decision.reason.lower()

    def test_rollback_high_lease_failure(self):
        metrics = SchedulerMetrics()
        for _ in range(5):
            metrics.record_lease_failure()
        decision = self.analyzer.analyze(metrics)
        assert not decision.can_promote
        assert "lease" in decision.reason.lower()

    def test_rollback_low_health_score(self):
        metrics = SchedulerMetrics()
        for _ in range(10):
            metrics.record_lease_failure()
        metrics.record_processing_time(120.0)
        metrics.observe_backlog(1000)
        decision = self.analyzer.analyze(metrics)
        assert not decision.can_promote

    def test_custom_thresholds(self):
        tight = CanaryThresholds(max_backlog_depth=5, max_processing_latency_p99=5.0)
        analyzer = CanaryAnalyzer(thresholds=tight)
        metrics = SchedulerMetrics()
        metrics.record_processing_time(3.0)
        # Latency 3s < 5s, but health is fine
        decision = analyzer.analyze(metrics, backlog_depth=3)
        assert decision.can_promote

    def test_decision_contains_diagnostics(self):
        metrics = SchedulerMetrics()
        metrics.record_lease_renewal()
        metrics.record_processing_time(1.5)
        decision = self.analyzer.analyze(metrics, backlog_depth=10)
        assert isinstance(decision, CanaryDecision)
        assert decision.backlog_depth == 10
        assert decision.p99_processing_latency == 1.5
        assert decision.health_score >= 0.0

    def test_multiple_failures_reported(self):
        metrics = SchedulerMetrics()
        for _ in range(10):
            metrics.record_lease_failure()
        metrics.record_processing_time(120.0)
        metrics.observe_backlog(500)
        decision = self.analyzer.analyze(metrics, backlog_depth=200)
        assert not decision.can_promote
        # Should mention at least 2 failure types
        assert ";" in decision.reason


class TestTaskSchedulerMetrics:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_updates_backlog(self):
        self.scheduler.enqueue({"type": "test"})
        assert self.scheduler.queue_depth() == 1
        assert self.scheduler.total_backlog() == 1

    def test_schedule_updates_backlog(self):
        self.scheduler.schedule({"type": "test"}, delay=3600)
        assert self.scheduler.total_backlog() == 1

    def test_metrics_integration(self):
        task_id = self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.complete(task["id"])
        metrics = self.scheduler.metrics
        assert metrics.lease_renewal_count >= 1
        assert metrics.avg_processing_time >= 0.0

    def test_fail_records_lease_failure(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        metrics = self.scheduler.metrics
        assert metrics.lease_failure_count >= 1

# 2026-05-10T14:00:00 test update
