import asyncio
import time

import pytest
from src.orchestrator.scheduler import (
    ClusterStartupGuard,
    ReconciliationAudit,
    TaskScheduler,
)


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_fail_task_exhausts_retries(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        # First fail — retries
        assert self.scheduler.fail(task["id"])
        task2 = asyncio.run(self.scheduler.dequeue())
        assert task2 is not None
        # Second fail — retries
        assert self.scheduler.fail(task2["id"])
        task3 = asyncio.run(self.scheduler.dequeue())
        assert task3 is not None
        # Third fail (exhausted)
        assert self.scheduler.fail(task3["id"])
        task4 = asyncio.run(self.scheduler.dequeue())
        assert task4 is None


class TestClusterStartupGuard:
    def test_initial_state_not_started(self):
        guard = ClusterStartupGuard()
        assert not guard.is_stable()
        assert guard.elapsed == 0.0

    def test_acquire_once(self):
        guard = ClusterStartupGuard()
        assert guard.try_acquire()
        assert not guard.try_acquire()

    def test_reset(self):
        guard = ClusterStartupGuard()
        guard.try_acquire()
        guard.reset()
        assert guard.try_acquire()

    def test_stable_after_stagger_window(self):
        guard = ClusterStartupGuard()
        guard.try_acquire()
        # Within window — not stable
        assert not guard.is_stable()
        # Advance time past the window
        guard._started_at = time.time() - guard._stagger_window - 1
        assert guard.is_stable()


class TestReconciliationAudit:
    def test_record_and_recent(self):
        audit = ReconciliationAudit(max_entries=10)
        audit.record("started", "default", 5, "test_start")
        audit.record("reconcile", "all", 3, "cycle=1")
        recent = audit.recent(2)
        assert len(recent) == 2
        assert recent[0]["decision"] == "started"

    def test_bounded_entries(self):
        audit = ReconciliationAudit(max_entries=5)
        for i in range(10):
            audit.record("reconcile", "all", i, f"cycle={i}")
        assert len(audit) == 5

    def test_empty_audit(self):
        audit = ReconciliationAudit()
        assert audit.recent(5) == []


class TestStaggeredReconciliation:
    def test_startup_guard_integration(self):
        scheduler = TaskScheduler(stagger_min=0.01, stagger_max=0.05)
        assert scheduler.startup_guard is not None

    @pytest.mark.asyncio
    async def test_reconciliation_promotes_expired(self):
        scheduler = TaskScheduler(stagger_min=0.01, stagger_max=0.05)
        scheduler.schedule({"type": "delayed"}, delay=-1)
        await scheduler._reconcile_once(cycle=0)
        assert len(scheduler._scheduled) == 0
        # The expired task should have been promoted to a queue
        task = await scheduler.dequeue()
        assert task is not None
        assert task["type"] == "delayed"

    @pytest.mark.asyncio
    async def test_reconciliation_reclaims_stale(self):
        scheduler = TaskScheduler(stagger_min=0.01, stagger_max=0.05)
        task_id = scheduler.enqueue({"type": "stale"})
        # Simulate it being in-flight for >60s
        task = await scheduler.dequeue()
        task["enqueued_at"] = time.time() - 120
        scheduler._in_flight[task_id] = task
        await scheduler._reconcile_once(cycle=0)
        # Should have been reclaimed back to queue
        reclaimed = await scheduler.dequeue()
        assert reclaimed is not None

    @pytest.mark.asyncio
    async def test_reconciliation_does_not_promote_future(self):
        scheduler = TaskScheduler(stagger_min=0.01, stagger_max=0.05)
        scheduler.schedule({"type": "future"}, delay=3600)
        await scheduler._reconcile_once(cycle=0)
        assert len(scheduler._scheduled) == 1

    @pytest.mark.asyncio
    async def test_reconciliation_audit_logged(self):
        scheduler = TaskScheduler(stagger_min=0.01, stagger_max=0.05)
        scheduler.enqueue({"type": "a"})
        scheduler.enqueue({"type": "b"})
        await scheduler._reconcile_once(cycle=1)
        recent = scheduler.audit.recent(1)
        assert len(recent) == 1
        assert recent[0]["decision"] == "reconcile"
        assert "cycle=1" in recent[0]["reason"]
