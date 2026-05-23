"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import datetime
import heapq
import time
from typing import Any, Dict, Optional, Union
from uuid import uuid4


def _to_timestamp(when: Union[float, datetime.datetime]) -> float:
    """Convert a timezone-aware datetime or float delay to a Unix timestamp.

    Accepts:
      - float: treated as delay in seconds from now → returns time.time() + delay
      - int: treated as delay in seconds from now
      - datetime.datetime (naive): treated as UTC
      - datetime.datetime (timezone-aware): normalized to UTC

    Raises TypeError for unsupported types.
    """
    if isinstance(when, (int, float)):
        return time.time() + when
    if isinstance(when, datetime.datetime):
        if when.tzinfo is not None:
            # Convert to UTC and get timestamp
            when_utc = when.astimezone(datetime.timezone.utc)
            return when_utc.timestamp()
        else:
            # Naive datetime — treat as UTC
            return when.replace(tzinfo=datetime.timezone.utc).timestamp()
    raise TypeError(f"Unsupported schedule type: {type(when).__name__}")


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

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(
        self,
        task: Dict,
        delay: Union[float, datetime.datetime],
        queue: str = "default",
        priority: int = 0,
    ) -> str:
        """Schedule a task for future execution.

        Args:
            task: The task dictionary.
            delay: Delay in seconds (float), or a datetime.datetime object.
                   Datetime objects should be timezone-aware for consistent
                   behavior across timezone boundaries.
            queue: Target queue name.
            priority: Task priority (higher = more urgent).

        Returns:
            The scheduled task ID.
        """
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = _to_timestamp(delay)
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
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False
