import pytest
from src.orchestrator.scheduler import TaskScheduler, Decision, LimiterAuditLog, CapacityLimiter, AuditEntry


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

    def test_enqueue_rejected_when_at_capacity(self):
        self.scheduler.limiter.set_max_queue_depth("default", 0)
        task_id = self.scheduler.enqueue({"type": "test"})
        assert task_id is None

    def test_dequeue_deferred_when_in_flight_at_capacity(self):
        self.scheduler.limiter.set_max_in_flight("default", 0)
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is None

    def test_schedule_rejected_when_at_capacity(self):
        self.scheduler.limiter.set_max_queue_depth("default", 0)
        task_id = self.scheduler.schedule({"type": "test"}, delay=0.1)
        assert task_id is None

    def test_audit_log_records_decisions(self):
        self.scheduler.limiter.set_max_queue_depth("default", 0)
        self.scheduler.enqueue({"type": "test"})
        trail = self.scheduler.get_audit_trail()
        assert len(trail) >= 1
        assert trail[0]["decision"] in ("allowed", "rejected", "deferred")

    def test_audit_log_no_private_data(self):
        self.scheduler.enqueue({"type": "test", "secret": "s3cr3t"})
        trail = self.scheduler.get_audit_trail()
        for entry in trail:
            assert "secret" not in entry
            assert entry.get("task_id") is None

    def test_limiter_rate_limit(self):
        self.scheduler.limiter.set_rate_limit("default", 10.0)
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None

        task2 = asyncio.run(self.scheduler.dequeue())
        assert task2 is None

    def test_audit_trail_capacity(self):
        log = LimiterAuditLog(max_entries=10)
        for _ in range(20):
            log.record(AuditEntry(
                timestamp="2026-01-01T00:00:00",
                decision="allowed", reason="test",
                queue="default",
            ))
        assert len(log) == 10
