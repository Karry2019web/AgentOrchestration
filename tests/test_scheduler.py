import pytest
from src.orchestrator.scheduler import TaskScheduler, BatchAckError


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


class TestBatchAcknowledgement:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def _dequeue_tasks(self, count=1, worker_id="worker-1"):
        """Helper to dequeue tasks using a specific worker."""
        import asyncio
        tasks = []
        for _ in range(count):
            self.scheduler.enqueue({"type": "test", "data": 1})
        for _ in range(count):
            task = asyncio.run(self.scheduler.dequeue(worker_id=worker_id))
            if task:
                tasks.append(task)
        return tasks

    def test_batch_acknowledge_all_owned(self):
        """Worker can acknowledge all its owned tasks in a batch."""
        tasks = self._dequeue_tasks(3, "worker-1")
        task_ids = [t["id"] for t in tasks]
        acked, rejected = self.scheduler.batch_acknowledge(task_ids, "worker-1")
        assert acked == 3
        assert rejected == []
        assert self.scheduler._in_flight_by_worker.get("worker-1", set()) == set()

    def test_batch_acknowledge_partial_rejected(self):
        """Tasks not owned by the worker are rejected."""
        tasks = self._dequeue_tasks(2, "worker-1")
        owned_ids = [t["id"] for t in tasks]
        foreign_ids = ["not-owned-1", "not-owned-2"]
        all_ids = owned_ids + foreign_ids
        acked, rejected = self.scheduler.batch_acknowledge(all_ids, "worker-1")
        assert acked == 2
        assert len(rejected) == 2
        assert "not-owned-1" in rejected

    def test_batch_acknowledge_wrong_worker_raises(self):
        """A worker with no in-flight tasks raises BatchAckError."""
        self._dequeue_tasks(1, "worker-1")
        with pytest.raises(BatchAckError, match="has no in-flight tasks"):
            self.scheduler.batch_acknowledge(["fake-id"], "worker-2")

    def test_batch_acknowledge_empty_list(self):
        """Empty task list returns zeros."""
        acked, rejected = self.scheduler.batch_acknowledge([], "any-worker")
        assert acked == 0
        assert rejected == []

    def test_batch_acknowledge_idempotent(self):
        """Acknowledging the same task twice is safe (second call is no-op)."""
        tasks = self._dequeue_tasks(1, "worker-1")
        task_id = tasks[0]["id"]
        acked1, rejected1 = self.scheduler.batch_acknowledge([task_id], "worker-1")
        assert acked1 == 1
        acked2, rejected2 = self.scheduler.batch_acknowledge([task_id], "worker-1")
        assert acked2 == 0
        assert task_id in rejected2

    def test_dequeue_with_worker_id_tracks_ownership(self):
        """Dequeued tasks are tracked under the correct worker."""
        import asyncio
        self.scheduler.enqueue({"type": "a"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="custom-worker"))
        assert task is not None
        assert "custom-worker" in self.scheduler._in_flight_by_worker
        assert task["id"] in self.scheduler._in_flight_by_worker["custom-worker"]

    def test_complete_cleans_worker_tracking(self):
        """Completing a task removes it from the worker tracking set."""
        import asyncio
        self.scheduler.enqueue({"type": "a"})
        task = asyncio.run(self.scheduler.dequeue(worker_id="w1"))
        self.scheduler.complete(task["id"])
        assert task["id"] not in self.scheduler._in_flight_by_worker.get("w1", set())
