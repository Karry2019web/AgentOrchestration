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

    def test_complete_idempotent(self):
        """Calling complete() multiple times is safe."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"]) is True
        assert self.scheduler.complete(task["id"]) is True

    def test_fail_already_completed(self):
        """Failing an already-completed task returns False."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.complete(task["id"])
        assert self.scheduler.fail(task["id"]) is False

    def test_dequeue_tracks_worker_id(self):
        """Dequeue with worker_id records ownership."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        assert task is not None
        assert task["worker_id"] == "worker-1"
        assert task["id"] in self.scheduler._batch_owners.get("worker-1", set())

    def test_complete_batch_acknowledges_owned_tasks(self):
        """complete_batch acknowledges tasks owned by the worker."""
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        t2 = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        result = self.scheduler.complete_batch([t1["id"], t2["id"]], worker_id="worker-1")
        assert len(result["acknowledged"]) == 2
        assert len(result["rejected"]) == 0

    def test_complete_batch_rejects_unowned(self):
        """complete_batch rejects tasks not owned by the worker."""
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        t2 = asyncio.run(self.scheduler.dequeue(worker_id="worker-2"))
        result = self.scheduler.complete_batch([t1["id"], t2["id"]], worker_id="worker-1")
        assert len(result["acknowledged"]) == 1
        assert len(result["rejected"]) == 1
        assert result["acknowledged"] == [t1["id"]]
        assert result["rejected"] == [t2["id"]]

    def test_complete_batch_idempotent(self):
        """Calling complete_batch twice is safe."""
        self.scheduler.enqueue({"type": "a"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        result1 = self.scheduler.complete_batch([t1["id"]], worker_id="worker-1")
        result2 = self.scheduler.complete_batch([t1["id"]], worker_id="worker-1")
        assert len(result1["acknowledged"]) == 1
        assert len(result2["acknowledged"]) == 0  # already completed

    def test_complete_batch_without_worker_id(self):
        """complete_batch without worker_id acknowledges all."""
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        t2 = asyncio.run(self.scheduler.dequeue(worker_id="worker-2"))
        result = self.scheduler.complete_batch([t1["id"], t2["id"]])
        assert len(result["acknowledged"]) == 2
        assert len(result["rejected"]) == 0

    def test_get_batch_owner_returns_worker(self):
        """get_batch_owner returns the owning worker."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        owner = self.scheduler.get_batch_owner(task["id"])
        assert owner == "worker-1"

    def test_get_batch_owner_after_complete(self):
        """get_batch_owner returns None for completed task."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(worker_id="worker-1"))
        self.scheduler.complete(task["id"])
        owner = self.scheduler.get_batch_owner(task["id"])
        assert owner is None

    def test_in_flight_and_completed_counts(self):
        """Track counts of in-flight and completed tasks."""
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue())
        t2 = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.in_flight_count() == 2
        self.scheduler.complete(t1["id"])
        assert self.scheduler.in_flight_count() == 1
        assert self.scheduler.completed_count() == 1
        self.scheduler.complete(t2["id"])
        assert self.scheduler.in_flight_count() == 0
        assert self.scheduler.completed_count() == 2
