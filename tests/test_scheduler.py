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

    def test_worker_heartbeat(self):
        self.scheduler.worker_heartbeat("worker-a")
        assert self.scheduler.get_worker_count() == 1

    def test_dequeue_with_worker_assignment(self):
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        assert task["assigned_worker"] == "worker-a"

    def test_complete_rejects_wrong_worker(self):
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        assert not self.scheduler.complete(task["id"], worker_id="worker-b")
        assert self.scheduler.complete(task["id"], worker_id="worker-a")

    def test_fail_rejects_wrong_worker(self):
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        assert not self.scheduler.fail(task["id"], worker_id="worker-b")
        assert self.scheduler.fail(task["id"], worker_id="worker-a")

    def test_deregister_worker_reclaims_tasks(self):
        import asyncio
        self.scheduler.worker_heartbeat("worker-a")
        self.scheduler.enqueue({"type": "test-1"})
        self.scheduler.enqueue({"type": "test-2"})
        t1 = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        t2 = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        count = self.scheduler.deregister_worker("worker-a")
        assert count == 2

    def test_reclaim_abandoned_no_timeout(self):
        import asyncio
        self.scheduler.worker_heartbeat("worker-a")
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        reclaimed = self.scheduler.reclaim_abandoned(reservation_timeout=300.0)
        assert reclaimed == 0

    def test_reclaim_abandoned_with_timeout(self):
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-a"))
        reclaimed = self.scheduler.reclaim_abandoned(reservation_timeout=-1.0)
        assert reclaimed >= 1

    def test_get_in_flight_count(self):
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.get_in_flight_count() == 1
        self.scheduler.complete(task["id"])
        assert self.scheduler.get_in_flight_count() == 0
