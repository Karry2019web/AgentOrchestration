"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from datetime import datetime, timezone, timedelta
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
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

    def _normalize_delay(self, delay_or_datetime) -> float:
        """Normalize a delay/schedule to a seconds-from-now value.
        
        Accepts:
        - float/int: treated as seconds from now
        - datetime (naive): treated as UTC epoch target time
        - datetime (timezone-aware): converted to UTC then to seconds from now
        - timedelta: converted to total seconds
        """
        if isinstance(delay_or_datetime, (int, float)):
            return float(delay_or_datetime)
        if isinstance(delay_or_datetime, timedelta):
            return delay_or_datetime.total_seconds()
        if isinstance(delay_or_datetime, datetime):
            if delay_or_datetime.tzinfo is None:
                # Naive datetime — treat as UTC
                target_ts = delay_or_datetime.replace(tzinfo=timezone.utc).timestamp()
            else:
                target_ts = delay_or_datetime.timestamp()
            return max(0.0, target_ts - time.time())
        return float(delay_or_datetime)

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay, queue: str = "default", priority: int = 0) -> str:
        """Schedule a task with a delay or at a specific datetime.
        
        Args:
            task: Task payload dict
            delay: Seconds from now (float), timedelta, or datetime (naive=UTC, aware=converted)
            queue: Target queue name
            priority: Task priority
        """
        task_id = str(uuid4())
        task["id"] = task_id
        delay_seconds = self._normalize_delay(delay)
        self._scheduled[task_id] = time.time() + delay_seconds
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            if tid in self._scheduled:
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
