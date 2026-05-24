"""Task Scheduler — Priority-based task queuing and dispatch with capacity management."""

import asyncio
import heapq
import time
from typing import Any, Dict, Optional, Set
from uuid import uuid4


class PriorityQueue:
    def __init__(self, maxsize: int = 0):
        self._queue = []
        self._counter = 0
        self._maxsize = maxsize

    def push(self, item: Any, priority: int = 0) -> None:
        if self._maxsize > 0 and len(self._queue) >= self._maxsize:
            raise CapacityError("Queue capacity exceeded")
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


class CapacityError(Exception):
    """Raised when a queue has reached its maximum capacity."""


class TaskScheduler:
    def __init__(self, default_max_queue_size: int = 1000):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._default_max_queue_size = default_max_queue_size
        self._enqueuing: Set[str] = set()

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue(maxsize=self._default_max_queue_size)

        self._enqueuing.add(task_id)
        try:
            self._queues[queue].push(task, priority)
            return task_id
        except CapacityError:
            self._enqueuing.discard(task_id)
            raise
        finally:
            self._enqueuing.discard(task_id)

    def enqueue_rollback(self, task_id: str) -> None:
        """Release capacity reserved for a task that failed to enqueue."""
        self._enqueuing.discard(task_id)

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

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                try:
                    self.enqueue(task, queue, priority=task.get("priority", 0))
                except CapacityError:
                    return False
                return True
        return False

    def queue_size(self, queue: str = "default") -> int:
        if queue in self._queues:
            return len(self._queues[queue])
        return 0

    def in_flight_count(self) -> int:
        return len(self._in_flight)
