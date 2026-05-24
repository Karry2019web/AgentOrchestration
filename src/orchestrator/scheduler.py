"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import random
import time
from typing import Any, Dict, Optional
from uuid import uuid4


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
    def __init__(self, base_retry_delay: float = 1.0, max_retry_delay: float = 120.0, jitter_factor: float = 0.5):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._base_retry_delay = base_retry_delay
        self._max_retry_delay = max_retry_delay
        self._jitter_factor = jitter_factor

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
        return self._in_flight.pop(task_id, None) is not None

    def _compute_retry_delay(self, retry_count: int) -> float:
        """Compute exponential backoff delay with jitter for retries.
        
        Uses the formula: delay = min(base * 2^retry, max_delay) * (1 + uniform(-jitter, jitter))
        This spreads retries across time to avoid thundering herd problems.
        """
        base_delay = self._base_retry_delay * (2 ** retry_count)
        capped_delay = min(base_delay, self._max_retry_delay)
        jitter = 1 + random.uniform(-self._jitter_factor, self._jitter_factor)
        return capped_delay * jitter

    def fail(self, task_id: str, queue: str = "default", priority: int = 0) -> bool:
        """Mark a task as failed and schedule retry with jittered backoff.
        
        Returns True if the task will be retried, False if max retries exceeded.
        """
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                delay = self._compute_retry_delay(task["retries"])
                self.schedule(task, delay, queue, priority=priority)
                return True
        return False
