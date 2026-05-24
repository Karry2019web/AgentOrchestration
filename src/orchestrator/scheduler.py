"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, Optional
from uuid import uuid4

from src.common.errors import MalformedTaskPayloadError


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
    # Required fields for a valid task payload
    REQUIRED_FIELDS = {"type", "payload"}

    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._completed: set = set()
        self._max_retries = 3

    @staticmethod
    def _validate_payload(task: Dict) -> None:
        """Validate task payload before enqueueing.

        Rejects tasks with missing required fields or non-dict payloads.
        Raises MalformedTaskPayloadError for invalid payloads.
        """
        if not isinstance(task, dict):
            raise MalformedTaskPayloadError(
                "Task must be a dictionary",
                task_repr=str(task),
            )

        missing = TaskScheduler.REQUIRED_FIELDS - set(task.keys())
        if missing:
            raise MalformedTaskPayloadError(
                f"Missing required fields: {missing}",
                task_repr=str({k: v for k, v in task.items() if k != "payload"}),
            )

        payload = task.get("payload")
        if payload is not None and not isinstance(payload, dict):
            raise MalformedTaskPayloadError(
                "Task payload must be a dictionary or None",
                task_repr=str({k: v for k, v in task.items() if k != "payload"}),
            )

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        self._validate_payload(task)
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        self._validate_payload(task)
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
        task = self._in_flight.pop(task_id, None)
        if task:
            self._completed.add(task_id)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                # Idempotent re-enqueue: skip if already completed
                if task_id not in self._completed:
                    self.enqueue(task, queue, priority=task.get("priority", 0))
                    return True
        return False
