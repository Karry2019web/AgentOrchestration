"""Task Scheduler — Priority-based task queuing and dispatch with attempt-scoped retries."""

import asyncio
import heapq
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from src.orchestrator.retry import RetryTracker


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._retry_tracker = RetryTracker(max_retries=self._max_retries)

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        self._retry_tracker.reset(task_id)
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default", attempt_id: str = "default") -> bool:
        """Mark a task as failed and optionally re-enqueue for retry.

        Args:
            task_id: The task ID to fail.
            queue: Queue to re-enqueue onto if retrying.
            attempt_id: Scopes the retry counter per parallel branch attempt.
                         Use a unique attempt_id for each parallel branch execution
                         so retry budgets remain isolated.

        Returns:
            True if the task was re-enqueued for retry, False if max retries exceeded.
        """
        task = self._in_flight.pop(task_id, None)
        if task:
            self._retry_tracker.increment(task_id, attempt_id)
            count = self._retry_tracker.get_retry_count(task_id, attempt_id)
            task["retries"] = count
            if count < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def get_retry_count(self, task_id: str, attempt_id: str = "default") -> int:
        return self._retry_tracker.get_retry_count(task_id, attempt_id)

    def can_retry(self, task_id: str, attempt_id: str = "default") -> bool:
        return self._retry_tracker.can_retry(task_id, attempt_id)

    def remaining_retries(self, task_id: str, attempt_id: str = "default") -> int:
        return self._retry_tracker.remaining(task_id, attempt_id)

    def reset_task_retries(self, task_id: str) -> None:
        self._retry_tracker.reset(task_id)
