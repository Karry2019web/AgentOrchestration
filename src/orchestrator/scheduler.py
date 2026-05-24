"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

DEFAULT_RESERVATION_TTL = 60.0  # seconds before a reserved job is considered abandoned


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
    def __init__(self, reservation_ttl: float = DEFAULT_RESERVATION_TTL):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._reservation_ttl = reservation_ttl

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
                task["reserved_at"] = time.time()
                task["reservation_lease"] = self._reservation_ttl
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

    def reclaim_abandoned(self, queue: str = "default", grace_period: Optional[float] = None) -> int:
        """Reclaim reserved jobs whose reservation has expired (worker likely disconnected).

        Returns the number of jobs reclaimed.
        """
        if grace_period is None:
            grace_period = self._reservation_ttl
        now = time.time()
        reclaimed = 0
        stale_ids = [
            tid for tid, task in self._in_flight.items()
            if task.get("reserved_at", 0) + grace_period < now
        ]
        for tid in stale_ids:
            task = self._in_flight.pop(tid, None)
            if task is not None:
                task.pop("reserved_at", None)
                task.pop("reservation_lease", None)
                task["retries"] += 1
                task["reclaimed_at"] = now
                if task["retries"] < self._max_retries:
                    self.enqueue(task, queue, priority=0)
                logger.info(
                    "Reclaimed abandoned job %s (retries=%d)",
                    tid, task.get("retries", 0),
                )
                reclaimed += 1
        return reclaimed

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    @property
    def in_flight_ids(self) -> set:
        return set(self._in_flight.keys())
