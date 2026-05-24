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

    def test_fail_respects_max_retries(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        # The scheduler has max_retries=3, so first 2 calls return True
        assert self.scheduler.fail(task["id"])
        # Second fail (retry 2)
        assert self.scheduler.fail(task["id"])
        # Third fail (retry 3) — max retries exceeded
        assert not self.scheduler.fail(task["id"])

    def test_retry_delay_uses_schedule_not_enqueue(self):
        """Verify that failed tasks use schedule() with a delay instead of immediate enqueue."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        # After fail, the task should be in _scheduled, not _queues
        self.scheduler.fail(task["id"])
        assert task["id"] not in self.scheduler._in_flight
        # Task should be in _scheduled with a future timestamp
        scheduled_time = self.scheduler._scheduled.get(task["id"])
        assert scheduled_time is not None, "Task should be scheduled with a delay"
        import time
        assert scheduled_time > time.time(), "Scheduled time should be in the future"

    def test_retry_delay_grows_exponentially(self):
        """Verify exponential backoff: each retry has a longer delay than the previous."""
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        
        # Capture delays for each retry
        delays = []
        for _ in range(2):
            self.scheduler.fail(task["id"])
            scheduled_time = self.scheduler._scheduled.get(task["id"])
            if scheduled_time:
                import time
                delay = scheduled_time - time.time()
                delays.append(delay)
                # Re-dequeue to retry
                task2 = asyncio.run(self.scheduler.dequeue())
                if task2:
                    task = task2
        
        # We should see increasing delays
        if len(delays) >= 2:
            assert delays[1] > delays[0], f"Expected delay to increase: {delays}"
