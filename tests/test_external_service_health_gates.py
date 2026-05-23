"""Tests for ExternalServiceHealthGate and health-gated TaskScheduler deferral."""

import pytest
from src.orchestrator.scheduler import (
    ExternalServiceHealthGate,
    TaskScheduler,
    ServiceHealthEntry,
    DeferralEntry,
)


class TestExternalServiceHealthGate:
    def test_default_gate_is_open(self):
        gate = ExternalServiceHealthGate()
        assert gate.is_gate_open() is True
        assert gate.get_unhealthy_services() == []

    def test_mark_unhealthy_closes_gate(self):
        gate = ExternalServiceHealthGate()
        gate.mark_unhealthy("database", "connection timeout")
        assert gate.is_gate_open() is False
        assert gate.is_healthy("database") is False
        assert "database" in gate.get_unhealthy_services()

    def test_mark_healthy_opens_gate(self):
        gate = ExternalServiceHealthGate()
        gate.mark_unhealthy("redis", "cluster down")
        assert gate.is_gate_open() is False
        gate.mark_healthy("redis")
        assert gate.is_gate_open() is True
        assert gate.is_healthy("redis") is True

    def test_multiple_services(self):
        gate = ExternalServiceHealthGate()
        gate.mark_unhealthy("db", "timeout")
        gate.mark_unhealthy("cache", "unreachable")
        assert gate.is_gate_open() is False
        assert sorted(gate.get_unhealthy_services()) == ["cache", "db"]
        gate.mark_healthy("db")
        assert gate.is_gate_open() is False
        assert gate.get_unhealthy_services() == ["cache"]
        gate.mark_healthy("cache")
        assert gate.is_gate_open() is True

    def test_gate_status_snapshot(self):
        gate = ExternalServiceHealthGate()
        gate.mark_unhealthy("db", "timeout")
        gate.mark_healthy("queue")
        status = gate.gate_status()
        assert status["db"] is False
        assert status["queue"] is True

    def test_audit_log_records_decisions(self):
        gate = ExternalServiceHealthGate(max_audit_entries=64)
        gate.mark_unhealthy("db", "connection timeout")
        gate.mark_healthy("db")
        gate.mark_unhealthy("redis", "OOM")
        log = gate.get_audit_log()
        assert len(log) >= 3
        assert log[0].reason == "OOM"
        assert log[0].service_name == "redis"
        assert log[0].healthy is False

    def test_audit_log_bounded(self):
        gate = ExternalServiceHealthGate(max_audit_entries=5)
        for i in range(10):
            gate.mark_unhealthy(f"svc{i}", f"reason_{i}")
        log = gate.get_audit_log()
        assert len(log) <= 5

    def test_clear_resets_state(self):
        gate = ExternalServiceHealthGate()
        gate.mark_unhealthy("db", "timeout")
        assert gate.is_gate_open() is False
        gate.clear()
        assert gate.is_gate_open() is True
        assert gate.get_unhealthy_services() == []
        assert gate.get_audit_log() == []


class TestTaskSchedulerHealthGate:
    def test_enqueue_deferred_when_gate_closed(self):
        gate = ExternalServiceHealthGate()
        scheduler = TaskScheduler(health_gate=gate)
        gate.mark_unhealthy("database", "unreachable")
        result = scheduler.enqueue({"type": "test", "payload": {}})
        assert result is None, "enqueue should return None when gate is closed"

    def test_enqueue_succeeds_when_gate_open(self):
        scheduler = TaskScheduler()
        result = scheduler.enqueue({"type": "test", "payload": {}})
        assert result is not None, "enqueue should return task_id when gate is open"
        import asyncio
        task = asyncio.run(scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_schedule_deferred_when_gate_closed(self):
        gate = ExternalServiceHealthGate()
        scheduler = TaskScheduler(health_gate=gate)
        gate.mark_unhealthy("cache", "down")
        result = scheduler.schedule({"type": "deferred"}, delay=10.0)
        assert result is None, "schedule should return None when gate is closed"

    def test_schedule_succeeds_when_gate_open(self):
        scheduler = TaskScheduler()
        result = scheduler.schedule({"type": "future"}, delay=10.0)
        assert result is not None, "schedule should return task_id when gate is open"

    def test_deferral_log_records_reason(self):
        gate = ExternalServiceHealthGate()
        scheduler = TaskScheduler(health_gate=gate)
        gate.mark_unhealthy("database", "timeout")
        scheduler.enqueue({"type": "etl"})
        log = scheduler.get_deferral_log()
        assert len(log) == 1
        assert log[0].reason == "external_service_down"
        assert "database" in log[0].unhealthy_services
        assert log[0].task_type == "etl"

    def test_recovery_after_service_restored(self):
        gate = ExternalServiceHealthGate()
        scheduler = TaskScheduler(health_gate=gate)
        gate.mark_unhealthy("database", "down")
        assert scheduler.enqueue({"type": "a"}) is None
        gate.mark_healthy("database")
        task_id = scheduler.enqueue({"type": "b"})
        assert task_id is not None

    def test_health_gate_property(self):
        gate = ExternalServiceHealthGate()
        scheduler = TaskScheduler(health_gate=gate)
        assert scheduler.health_gate is gate

    def test_default_health_gate_created(self):
        scheduler = TaskScheduler()
        assert scheduler.health_gate is not None
        assert scheduler.health_gate.is_gate_open() is True
