import asyncio
import time

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

    def test_dequeue_tracks_reservation(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert task is not None
        reservation = self.scheduler.get_reservation(task["id"])
        assert reservation is not None
        assert reservation["worker_id"] == "worker-1"
        assert "reserved_at" in reservation

    def test_complete_clears_reservation(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert self.scheduler.active_reservations == 1
        self.scheduler.complete(task["id"])
        assert self.scheduler.active_reservations == 0

    def test_reclaim_abandoned_no_expired(self):
        """No expired reservations means nothing is reclaimed."""
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        # With lease_expiry=30 and no time passing, nothing should be reclaimed
        reclaimed = self.scheduler.reclaim_abandoned()
        assert reclaimed == 0

    def test_reclaim_abandoned_expired(self):
        """Reservations older than max_age are reclaimed."""
        scheduler = TaskScheduler(lease_expiry_seconds=0.0)  # expire immediately
        scheduler.enqueue({"type": "test"})
        task = asyncio.run(scheduler.dequeue(worker_id="worker-1"))
        assert scheduler.active_reservations == 1
        reclaimed = scheduler.reclaim_abandoned(worker_id="worker-1", max_age=0.0)
        assert reclaimed == 1
        assert scheduler.active_reservations == 0
        # Task should be back in the queue
        requeued = asyncio.run(scheduler.dequeue())
        assert requeued is not None
        assert requeued["type"] == "test"

    def test_reclaim_abandoned_worker_filter(self):
        """Only reclaim reservations for the specified worker."""
        scheduler = TaskScheduler(lease_expiry_seconds=0.0)
        scheduler.enqueue({"type": "task-a"})
        scheduler.enqueue({"type": "task-b"})
        task_a = asyncio.run(scheduler.dequeue(worker_id="worker-1"))
        task_b = asyncio.run(scheduler.dequeue(worker_id="worker-2"))
        assert scheduler.active_reservations == 2
        # Only reclaim worker-1's abandoned tasks
        reclaimed = scheduler.reclaim_abandoned(worker_id="worker-1", max_age=0.0)
        assert reclaimed == 1
        assert scheduler.active_reservations == 1

    def test_reclaim_abandoned_all_workers(self):
        """Without worker_id filter, reclaim all expired reservations."""
        scheduler = TaskScheduler(lease_expiry_seconds=0.0)
        scheduler.enqueue({"type": "task-a"})
        scheduler.enqueue({"type": "task-b"})
        asyncio.run(scheduler.dequeue(worker_id="worker-1"))
        asyncio.run(scheduler.dequeue(worker_id="worker-2"))
        reclaimed = scheduler.reclaim_abandoned(max_age=0.0)
        assert reclaimed == 2
        assert scheduler.active_reservations == 0

    def test_reclaim_abandoned_max_retries_eventually_drops(self):
        """A task reclaimed up to max_retries times is dropped, not re-queued."""
        scheduler = TaskScheduler(lease_expiry_seconds=0.0)
        scheduler._max_retries = 2
        task_id = scheduler.enqueue({"type": "flaky"})
        # Dequeue and reclaim twice = retries go from 0->1->2 (max)
        asyncio.run(scheduler.dequeue(worker_id="worker-1"))
        scheduler.reclaim_abandoned(worker_id="worker-1", max_age=0.0)
        assert scheduler.in_flight_count == 0
        # Second dequeue: retries=1 so still eligible
        asyncio.run(scheduler.dequeue(worker_id="worker-1"))
        scheduler.reclaim_abandoned(worker_id="worker-1", max_age=0.0)
        # After 2 retries, max_retries=2 means it should be dropped
        assert scheduler.in_flight_count == 0
        assert scheduler.active_reservations == 0
        # No more tasks in queue
        nothing = asyncio.run(scheduler.dequeue())
        assert nothing is None
