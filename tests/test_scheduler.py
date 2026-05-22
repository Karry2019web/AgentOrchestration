"""Tests for HealthGate — verifies defer runs during dependency outages."""

import time
import pytest
from src.orchestrator.scheduler import HealthGate, HealthStatus


class TestHealthStatus:
    def test_starts_healthy(self):
        hs = HealthStatus("db")
        assert hs.is_healthy is True

    def test_failure_threshold_marks_unhealthy(self):
        hs = HealthStatus("api", check_interval=60)
        hs.record_failure()
        hs.record_failure()
        assert hs.is_healthy is True  # Not yet at threshold
        hs.record_failure()
        assert hs.is_healthy is False  # Reached max_failures=3

    def test_success_resets_failures(self):
        hs = HealthStatus("cache")
        hs.record_failure()
        hs.record_failure()
        hs.record_success()
        assert hs.is_healthy is True
        assert hs._consecutive_failures == 0

    def test_is_stale_after_check_interval(self):
        hs = HealthStatus("queue", check_interval=0.01)
        hs.record_success()
        time.sleep(0.03)
        assert hs.is_stale is True

    def test_reset_restores_health(self):
        hs = HealthStatus("db")
        hs.record_failure()
        hs.record_failure()
        hs.record_failure()
        assert hs.is_healthy is False
        hs.reset()
        assert hs.is_healthy is True


class TestHealthGate:
    def test_register_service(self):
        gate = HealthGate()
        hs = gate.register("database")
        assert hs is gate.get_status("database")

    def test_check_healthy_probe(self):
        gate = HealthGate()
        gate.register("api")
        result = gate.check("api", lambda: True)
        assert result is True
        assert gate.can_schedule("api") is True

    def test_check_unhealthy_probe(self):
        gate = HealthGate()
        gate.register("api")
        for _ in range(3):
            gate.check("api", lambda: False)
        assert gate.can_schedule("api") is False

    def test_check_exception_probe(self):
        gate = HealthGate()
        gate.register("api")

        def failing_probe():
            raise ConnectionError("timeout")

        for _ in range(3):
            gate.check("api", failing_probe)
        assert gate.can_schedule("api") is False

    def test_defer_and_release(self):
        gate = HealthGate()
        gate.register("db")
        for _ in range(3):
            gate.check("db", lambda: False)

        task = {"id": "task-1", "type": "process"}
        gate.defer(task, "db", reason="db_outage")
        assert gate.count_deferred() == 1

        released = gate.release_deferred("db")
        assert len(released) == 1
        assert released[0]["id"] == "task-1"
        assert gate.count_deferred() == 0

    def test_unknown_service_allows_scheduling(self):
        gate = HealthGate()
        assert gate.can_schedule("unknown") is True

    def test_all_unhealthy(self):
        gate = HealthGate()
        gate.register("db")
        gate.register("api")
        for _ in range(3):
            gate.check("db", lambda: False)
        assert gate.all_unhealthy() == ["db"]

    def test_deferred_tasks_released_after_recovery(self):
        gate = HealthGate()
        gate.register("redis")
        for _ in range(3):
            gate.check("redis", lambda: False)

        for i in range(3):
            gate.defer({"id": f"task-{i}"}, "redis", reason="redis_down")

        assert gate.count_deferred() == 3

        # Service recovers
        gate.check("redis", lambda: True)
        released = gate.release_deferred("redis")
        assert len(released) == 3

    def test_concurrent_defer_across_multiple_services(self):
        gate = HealthGate()
        gate.register("db")
        gate.register("cache")
        for svc in ["db", "cache"]:
            for _ in range(3):
                gate.check(svc, lambda: False)

        gate.defer({"id": "task-a"}, "db")
        gate.defer({"id": "task-b"}, "cache")
        gate.defer({"id": "task-c"}, "db")

        assert gate.count_deferred() == 3
        assert len(gate.release_deferred("db")) == 2
        assert len(gate.release_deferred("cache")) == 1
