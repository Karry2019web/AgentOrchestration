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


"""Tests for poison job redelivery throttling in TaskScheduler."""

import time
import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestPoisonJobThrottling:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_normal_failure_retries_without_throttle(self):
        """Failures below threshold should retry normally without cooldown."""
        import asyncio
        tid = self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])
        assert not self.scheduler.is_poisoned(task["id"])

    def test_poison_threshold_triggers_cooldown(self):
        """After poison_threshold consecutive failures, cooldown should activate."""
        import asyncio
        self.scheduler._poison_threshold = 2
        tid = self.scheduler.enqueue({"type": "poison"})
        for i in range(3):
            task = asyncio.run(self.scheduler.dequeue())
            if task:
                self.scheduler.fail(task["id"])
        assert self.scheduler.is_poisoned(tid)

    def test_poisoned_task_not_returned_by_dequeue(self):
        """A task in cooldown should not be returned by dequeue."""
        import asyncio
        self.scheduler._poison_threshold = 1
        self.scheduler._poison_cooldown_base = 3600  # 1 hour cooldown
        tid = self.scheduler.enqueue({"type": "poison"})
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        # Should be in cooldown now, dequeue should return None
        result = asyncio.run(self.scheduler.dequeue())
        assert result is None

    def test_cooldown_expires_and_task_becomes_available(self):
        """After cooldown expires, the task should be dequeuable again."""
        import asyncio
        self.scheduler._poison_threshold = 1
        self.scheduler._poison_cooldown_base = 0.01  # Very short cooldown
        tid = self.scheduler.enqueue({"type": "poison"})
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        # Cooldown should be very short
        assert self.scheduler.is_poisoned(tid)
        time.sleep(0.05)
        assert not self.scheduler.is_poisoned(tid)
        # Should be available now
        result = asyncio.run(self.scheduler.dequeue())
        assert result is not None

    def test_complete_resets_poison_strikes(self):
        """A successful complete should reset poison strikes."""
        import asyncio
        self.scheduler._poison_threshold = 2
        tid = self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        # Strike = 1, below threshold
        task2 = asyncio.run(self.scheduler.dequeue())
        self.scheduler.complete(task2["id"])
        # Next failure should not trigger cooldown since strikes were reset
        task3 = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task3["id"])
        assert not self.scheduler.is_poisoned(task3["id"])

    def test_max_retries_sends_to_dead_letter(self):
        """Exhausting max retries should send task to dead letter queue."""
        import asyncio
        self.scheduler._max_retries = 1
        tid = self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        assert self.scheduler.dead_letter_count() == 1

    def test_poison_cooldown_exponential_backoff(self):
        """Each subsequent poison strike should increase cooldown exponentially."""
        import asyncio
        self.scheduler._poison_threshold = 1
        self.scheduler._poison_cooldown_base = 10.0
        tid = self.scheduler.enqueue({"type": "poison"})
        # First poison
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        cd1 = self.scheduler._poison_cooldowns[tid]
        # Manually expire and fail again
        task2 = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task2["id"])
        cd2 = self.scheduler._poison_cooldowns.get(task2["id"], 0)
        assert cd2 > cd1  # Exponential backoff

    def test_dead_letter_list_contents(self):
        """dead_letter list should contain the actual task data."""
        import asyncio
        self.scheduler._max_retries = 1
        tid = self.scheduler.enqueue({"type": "test", "payload": {"key": "val"}})
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        dead = self.scheduler.list_dead_letters()
        assert len(dead) == 1
        assert dead[0]["type"] == "test"
        assert dead[0]["payload"]["key"] == "val"
