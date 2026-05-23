"""Task Scheduler — Priority-based task queuing and dispatch."""

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
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def batch_acknowledge(self, task_ids, worker_id=None):
        """Validate batch acknowledgement ownership.
        
        Enforces that only the assigned worker can acknowledge tasks.
        Idempotent: already-acknowledged tasks return as rejected.
        
        Returns dict with acknowledged (list) and rejected (list of dicts).
        """
        acknowledged = []
        rejected = []
        for task_id in task_ids:
            task = self._in_flight.get(task_id)
            if not task:
                rejected.append({"id": task_id, "reason": "not_in_flight"})
                continue
            tw = task.get("assigned_worker")
            if tw and worker_id and tw != worker_id:
                rejected.append({"id": task_id, "reason": "ownership_mismatch", "owner": tw})
                continue
            self._in_flight.pop(task_id, None)
            acknowledged.append(task_id)
        return {"acknowledged": acknowledged, "rejected": rejected, "timestamp": time.time()}

    def complete(self, task_id, worker_id=None):
        """Mark task completed with optional ownership check."""
        task = self._in_flight.get(task_id)
        if not task:
            return False
        if worker_id and task.get("assigned_worker") and task["assigned_worker"] != worker_id:
            return False
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id, queue="default", worker_id=None):
        """Mark task failed with optional ownership check and retry."""
        task = self._in_flight.get(task_id)
        if not task:
            return False
        if worker_id and task.get("assigned_worker") and task["assigned_worker"] != worker_id:
            return False
        self._in_flight.pop(task_id, None)
        task["retries"] += 1
        if task["retries"] < self._max_retries:
            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        return False
