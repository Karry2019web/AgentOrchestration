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

    def test_complete_idempotent(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])
        assert self.scheduler.complete(task["id"])

    def test_fail_and_dead_letter(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(task["id"])
            task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        dl = self.scheduler.list_dead_letter()
        assert len(dl) == 1

    def test_fail_after_acknowledge(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.complete(task["id"])
        assert self.scheduler.fail(task["id"]) is False

    def test_dead_letter_acknowledge(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(task["id"])
            task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        assert self.scheduler.acknowledge_dead_letter(task["id"])
        assert self.scheduler.acknowledge_dead_letter(task["id"])

    def test_dead_letter_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(task["id"])
            task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        assert self.scheduler.retry_dead_letter(task["id"])
        retried = asyncio.run(self.scheduler.dequeue())
        assert retried is not None
        assert retried.get("dead_letter_retry") is True

    def test_dead_letter_retry_idempotent(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(task["id"])
            task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        assert self.scheduler.retry_dead_letter(task["id"])
        assert self.scheduler.retry_dead_letter(task["id"]) is False

    def test_dead_letter_count_by_reason(self):
        self.scheduler.enqueue({"type": "a"})
        self.scheduler.enqueue({"type": "b"})
        import asyncio
        t1 = asyncio.run(self.scheduler.dequeue())
        t2 = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(t1["id"]); t1 = asyncio.run(self.scheduler.dequeue())
            self.scheduler.fail(t2["id"]); t2 = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(t1["id"]); self.scheduler.fail(t2["id"])
        counts = self.scheduler.dead_letter_count()
        assert counts.get("max_retries_exceeded", 0) >= 2

    def test_unknown_dead_letter_acknowledge(self):
        assert self.scheduler.acknowledge_dead_letter("nonexistent") is False

    def test_list_dead_letter_empty(self):
        assert self.scheduler.list_dead_letter() == []

    def test_list_dead_letter_after_acknowledge(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        for _ in range(2):
            self.scheduler.fail(task["id"])
            task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        self.scheduler.acknowledge_dead_letter(task["id"])
        dl = self.scheduler.list_dead_letter()
        assert dl[0]["acknowledged"] is True

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])
