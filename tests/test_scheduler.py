import pytest
from src.orchestrator.scheduler import TaskScheduler, CapacityError


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

    def test_enqueue_exceeds_capacity(self):
        scheduler = TaskScheduler(default_max_queue_size=2)
        scheduler.enqueue({"type": "a"})
        scheduler.enqueue({"type": "b"})
        with pytest.raises(CapacityError):
            scheduler.enqueue({"type": "c"})

    def test_enqueue_rollback_releases_capacity(self):
        scheduler = TaskScheduler(default_max_queue_size=1)
        scheduler.enqueue({"type": "a"})
        scheduler.enqueue_rollback("test-id")
        tid2 = scheduler.enqueue({"type": "b"})
        assert tid2 is not None

    def test_queue_size_tracking(self):
        assert self.scheduler.queue_size() == 0
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        assert self.scheduler.queue_size() == 2

    def test_fail_task_preserves_capacity(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        task_a = asyncio.run(self.scheduler.dequeue())
        task_b = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task_a["id"])
        assert self.scheduler.queue_size() == 1

    def test_in_flight_count(self):
        assert self.scheduler.in_flight_count() == 0
        self.scheduler.enqueue({"type": "a"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.in_flight_count() == 1
        self.scheduler.complete(task["id"])
        assert self.scheduler.in_flight_count() == 0

    def test_dequeue_empty_queue(self):
        import asyncio
        result = asyncio.run(self.scheduler.dequeue())
        assert result is None
