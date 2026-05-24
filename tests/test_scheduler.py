import pytest
from src.orchestrator.scheduler import TaskScheduler


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

    def test_dequeue_adds_reservation_lease(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert "reserved_at" in task
        assert task["reservation_lease"] == 60.0

    def test_reclaim_abandoned_noop_when_none_stale(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        asyncio.run(self.scheduler.dequeue())
        count = self.scheduler.reclaim_abandoned(grace_period=3600.0)
        assert count == 0

    def test_reclaim_abandoned_recovers_stale_job(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        # Manually age the reservation
        self.scheduler._in_flight[task_id]["reserved_at"] = 0.0
        count = self.scheduler.reclaim_abandoned(grace_period=1.0)
        assert count == 1
        assert task_id not in self.scheduler._in_flight

    def test_reclaim_abandoned_respects_max_retries(self):
        self.scheduler._max_retries = 1
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler._in_flight[task["id"]]["reserved_at"] = 0.0
        # First reclaim
        count1 = self.scheduler.reclaim_abandoned(grace_period=1.0)
        assert count1 == 1
        # Dequeue the reclaimed job
        task2 = asyncio.run(self.scheduler.dequeue())
        assert task2 is not None
        self.scheduler._in_flight[task2["id"]]["reserved_at"] = 0.0
        # Second reclaim — should hit max_retries, no requeue
        count2 = self.scheduler.reclaim_abandoned(grace_period=1.0)
        assert count2 == 1
        # Now the queue should be empty, nothing left
        task3 = asyncio.run(self.scheduler.dequeue())
        assert task3 is None

    def test_reclaim_abandoned_multiple_tasks(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        self.scheduler.enqueue({"type": "c"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue())
        t2 = asyncio.run(self.scheduler.dequeue())
        t3 = asyncio.run(self.scheduler.dequeue())
        # Age all three reservations
        self.scheduler._in_flight[t1["id"]]["reserved_at"] = 0.0
        self.scheduler._in_flight[t2["id"]]["reserved_at"] = 0.0
        self.scheduler._in_flight[t3["id"]]["reserved_at"] = 0.0
        count = self.scheduler.reclaim_abandoned(grace_period=1.0)
        assert count == 3

    def test_in_flight_count_property(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        asyncio.run(self.scheduler.dequeue())
        asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.in_flight_count == 2
