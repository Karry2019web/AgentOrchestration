"""Task Scheduler --- Priority-based task queuing and dispatch."""

import asyncio
import heapq
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
    RESERVATION_TIMEOUT = 300

    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._reservations: Dict[str, Dict] = {}
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

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0, worker_id: Optional[str] = None) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)
        self._sweep_abandoned()
        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task_id = task["id"]
                self._in_flight[task_id] = task
                self._reservations[task_id] = {"worker_id": worker_id or "unknown", "reserved_at": now}
                return task
        return None

    def complete(self, task_id: str) -> bool:
        self._reservations.pop(task_id, None)
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        self._reservations.pop(task_id, None)
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def release_reservation(self, task_id: str, queue: str = "default") -> bool:
        self._reservations.pop(task_id, None)
        task = self._in_flight.pop(task_id, None)
        if task:
            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        return False

    def sweep_abandoned(self) -> int:
        return self._sweep_abandoned()

    def _sweep_abandoned(self) -> int:
        now = time.time()
        abandoned = [tid for tid, res in self._reservations.items() if now - res["reserved_at"] > self.RESERVATION_TIMEOUT]
        reclaimed = 0
        for tid in abandoned:
            task = self._in_flight.pop(tid, None)
            self._reservations.pop(tid, None)
            if task and task.get("retries", 0) < self._max_retries:
                task["retries"] = task.get("retries", 0) + 1
                self.enqueue(task, queue="default", priority=task.get("priority", 0))
                reclaimed += 1
        return reclaimed

    @property
    def active_reservations(self) -> int:
        return len(self._reservations)
