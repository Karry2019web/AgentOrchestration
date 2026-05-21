"""Tests for abandoned job reclamation in TaskScheduler."""

import time
import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestAbandonedTaskReclamation:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_reclaim_abandoned_re_enqueues_task(self):
        """Reclaiming a reserved task should re-enqueue it."""
        import asyncio
        tid = self.scheduler.enqueue({"type": "test", "payload": {}})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert task is not None
        tid = task["id"]

        reclaimed = self.scheduler.reclaim_abandoned("worker-1", timeout=0)
        assert len(reclaimed) == 1
        assert reclaimed[0]["id"] == tid
        assert reclaimed[0].get("_abandoned") is True

    def test_reclaim_abandoned_removes_reservation(self):
        """After reclamation, the task reservation should be cleared."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        self.scheduler.reclaim_abandoned("worker-1", timeout=0)
        # Second reclaim should return empty
        reclaimed = self.scheduler.reclaim_abandoned("worker-1", timeout=0)
        assert len(reclaimed) == 0

    def test_reclaim_abandoned_respects_timeout(self):
        """Tasks dequeued within the timeout window should not be reclaimed."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        # timeout=3600 means nothing is abandoned yet
        reclaimed = self.scheduler.reclaim_abandoned("worker-1", timeout=3600)
        assert len(reclaimed) == 0

    def test_reclaim_only_own_worker_tasks(self):
        """Reclaim should only affect tasks reserved by the specified worker."""
        import asyncio
        self.scheduler.enqueue({"type": "task-a"})
        self.scheduler.enqueue({"type": "task-b"})
        asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        asyncio.run(self.scheduler.dequeue(worker_id="worker-2"))

        reclaimed = self.scheduler.reclaim_abandoned("worker-1", timeout=0)
        assert len(reclaimed) == 1
        assert reclaimed[0]["type"] == "task-a"

    def test_reclaim_all_abandoned(self):
        """reclaim_all_abandoned should reclaim all timed-out tasks."""
        import asyncio
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        asyncio.run(self.scheduler.dequeue(worker_id="w1"))
        asyncio.run(self.scheduler.dequeue(worker_id="w2"))

        reclaimed = self.scheduler.reclaim_all_abandoned(timeout=0)
        assert len(reclaimed) == 2

    def test_complete_with_wrong_worker_returns_false(self):
        """Attempting to complete another worker's task should fail."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert self.scheduler.complete(task["id"], worker_id="worker-2") is False
        # Original worker should still be able to complete
        assert self.scheduler.complete(task["id"], worker_id="worker-1") is True

    def test_fail_with_wrong_worker_returns_false(self):
        """Attempting to fail another worker's task should fail."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert self.scheduler.fail(task["id"], worker_id="worker-2") is False
        # Original worker can still fail
        assert self.scheduler.fail(task["id"], worker_id="worker-1") is True

    def test_worker_disconnect_no_abandoned(self):
        """If a worker has no reserved tasks, reclaim returns empty."""
        reclaimed = self.scheduler.reclaim_abandoned("worker-unknown", timeout=0)
        assert len(reclaimed) == 0

    def test_reclaim_respects_max_retries(self):
        """After max retries exhausted, reclaimed tasks are not re-enqueued."""
        import asyncio
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="w1"))
        tid = task["id"]
        self.scheduler._max_retries = 0
        self.scheduler._in_flight[tid] = task
        self.scheduler._reservations[tid] = "w1"
        reclaimed = self.scheduler.reclaim_abandoned("w1", timeout=0)
        assert len(reclaimed) == 0  # Max retries exhausted, not re-enqueued
