import pytest
import time
from src.orchestrator.scheduler import TaskScheduler, ExternalServiceHealthGate, ServiceHealth


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])


class TestExternalServiceHealthGate:
    def test_register_service_defaults_healthy(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("api-gateway")
        assert gate.get_health("api-gateway") == ServiceHealth.HEALTHY
        assert gate.can_dispatch("api-gateway") is True

    def test_unreachable_service_blocks_dispatch(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("database")
        gate.update_health("database", ServiceHealth.UNREACHABLE)
        assert gate.can_dispatch("database") is False

    def test_degraded_service_blocks_dispatch(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("cache")
        gate.update_health("cache", ServiceHealth.DEGRADED)
        assert gate.can_dispatch("cache") is False

    def test_recovered_service_allows_dispatch(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("queue")
        gate.update_health("queue", ServiceHealth.UNREACHABLE)
        assert gate.can_dispatch("queue") is False
        gate.update_health("queue", ServiceHealth.HEALTHY)
        assert gate.can_dispatch("queue") is True

    def test_defer_task_when_service_unavailable(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("external-api")
        gate.update_health("external-api", ServiceHealth.UNREACHABLE)
        task = {"id": "task-1", "type": "sync"}
        result = gate.defer_task(task, "external-api")
        assert result is True
        assert gate.get_deferred_count("external-api") == 1

    def test_recover_deferred_after_health_restored(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("database")
        gate.update_health("database", ServiceHealth.UNREACHABLE)
        task = {"id": "task-db", "type": "query"}
        gate.defer_task(task, "database")
        gate.update_health("database", ServiceHealth.HEALTHY)
        recovered = gate.recover_deferred("database")
        assert len(recovered) == 1
        assert recovered[0]["id"] == "task-db"
        assert gate.get_deferred_count("database") == 0

    def test_service_not_registered_defaults_healthy(self):
        gate = ExternalServiceHealthGate()
        assert gate.get_health("unknown-service") == ServiceHealth.HEALTHY
        assert gate.can_dispatch("unknown-service") is True

    def test_max_retry_exceeded_rejects_deferral(self):
        gate = ExternalServiceHealthGate(max_retry_attempts=2)
        gate.register_service("flaky-service")
        gate.update_health("flaky-service", ServiceHealth.UNREACHABLE)
        task = {"id": "flaky-1", "type": "retry"}
        assert gate.defer_task(task, "flaky-service") is True
        assert gate.defer_task(task, "flaky-service") is False

    def test_recover_deferred_noop_on_no_recovery(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("external-api")
        gate.update_health("external-api", ServiceHealth.UNREACHABLE)
        task = {"id": "t1", "type": "sync"}
        gate.defer_task(task, "external-api")
        recovered = gate.recover_deferred("external-api")
        assert len(recovered) == 0

    def test_deferred_count_total(self):
        gate = ExternalServiceHealthGate()
        gate.register_service("svc-a")
        gate.register_service("svc-b")
        gate.update_health("svc-a", ServiceHealth.UNREACHABLE)
        gate.update_health("svc-b", ServiceHealth.UNREACHABLE)
        gate.defer_task({"id": "a1"}, "svc-a")
        gate.defer_task({"id": "a2"}, "svc-a")
        gate.defer_task({"id": "b1"}, "svc-b")
        assert gate.get_deferred_count() == 3
        assert gate.get_deferred_count("svc-a") == 2
        assert gate.get_deferred_count("svc-b") == 1

    def test_should_recheck_after_interval(self):
        gate = ExternalServiceHealthGate(check_interval=0.1)
        gate.register_service("api")
        gate._last_check["api"] = 0.0
        assert gate.should_recheck("api") is True
        gate._last_check["api"] = time.time()
        assert gate.should_recheck("api") is False
        time.sleep(0.15)
        assert gate.should_recheck("api") is True


class TestSchedulerWithHealthGate:
    def test_schedule_defers_when_service_unavailable(self):
        scheduler = TaskScheduler()
        gate = scheduler.health_gate
        gate.register_service("database")
        gate.update_health("database", ServiceHealth.UNREACHABLE)
        task_id = scheduler.schedule(
            {"type": "db-backup"}, delay=0.1,
            required_service="database"
        )
        assert task_id is not None
        assert gate.get_deferred_count("database") == 1

    def test_schedule_directly_when_service_healthy(self):
        scheduler = TaskScheduler()
        gate = scheduler.health_gate
        gate.register_service("database")
        task_id = scheduler.schedule(
            {"type": "db-backup"}, delay=0.1,
            required_service="database"
        )
        assert task_id is not None
        assert gate.get_deferred_count("database") == 0
        assert task_id in scheduler._scheduled

    def test_dequeue_checks_health_and_defers(self):
        scheduler = TaskScheduler()
        gate = scheduler.health_gate
        gate.register_service("external-api")
        scheduler.enqueue({"type": "sync", "_required_service": "external-api"})
        gate.update_health("external-api", ServiceHealth.UNREACHABLE)
        import asyncio
        task = asyncio.run(scheduler.dequeue())
        assert task is None
        assert gate.get_deferred_count("external-api") == 1

    def test_schedule_without_service_works_normally(self):
        scheduler = TaskScheduler()
        task_id = scheduler.schedule({"type": "normal-task"}, delay=0.1)
        assert task_id is not None
        assert task_id in scheduler._scheduled

    def test_health_gate_property_returns_instance(self):
        scheduler = TaskScheduler()
        assert isinstance(scheduler.health_gate, ExternalServiceHealthGate)

    def test_recovered_deferred_tasks_available_via_gate(self):
        scheduler = TaskScheduler()
        gate = scheduler.health_gate
        gate.register_service("queue")
        gate.update_health("queue", ServiceHealth.UNREACHABLE)
        scheduler.schedule({"type": "process-queue"}, delay=0.1, required_service="queue")
        gate.update_health("queue", ServiceHealth.HEALTHY)
        recovered = gate.recover_deferred("queue")
        assert len(recovered) == 1
        assert recovered[0]["type"] == "process-queue"
