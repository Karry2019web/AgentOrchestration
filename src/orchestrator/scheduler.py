"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


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
        self._scheduled: Dict[str, Dict] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._batch_owners: Dict[str, set] = {}
        self._completed: set = set()
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
        task["scheduled_at"] = time.time() + delay
        self._scheduled[task_id] = task
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0,
                      worker_id: Optional[str] = None) -> Optional[Dict]:
        now = time.time()
        expired_ids = [tid for tid, t in self._scheduled.items()
                       if isinstance(t, dict) and "scheduled_at" in t and t["scheduled_at"] <= now]
        for tid in expired_ids:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task_id = task["id"]
                task["worker_id"] = worker_id
                task["dequeued_at"] = time.time()
                self._in_flight[task_id] = task
                if worker_id:
                    self._batch_owners.setdefault(worker_id, set()).add(task_id)
                return task
        return None

    def complete(self, task_id: str) -> bool:
        """Acknowledge a task as completed. Idempotent — safe to call multiple times."""
        if task_id in self._completed:
            return True
        task = self._in_flight.pop(task_id, None)
        if task is not None:
            worker_id = task.get("worker_id")
            if worker_id and worker_id in self._batch_owners:
                self._batch_owners[worker_id].discard(task_id)
            self._completed.add(task_id)
            return True
        return False

    def complete_batch(self, task_ids: List[str],
                       worker_id: Optional[str] = None) -> Dict[str, Any]:
        """Acknowledge a batch of tasks. Validates ownership for the given worker."""
        results = {"acknowledged": [], "rejected": []}

        for task_id in task_ids:
            # Already completed — idempotent
            if task_id in self._completed:
                results["acknowledged"].append(task_id)
                continue

            # Check ownership if worker specified
            if worker_id and task_id in self._in_flight:
                owned = self._batch_owners.get(worker_id, set())
                if task_id not in owned:
                    logger.warning(
                        "Worker %s attempted to acknowledge task %s which is owned by another worker",
                        worker_id, task_id,
                    )
                    results["rejected"].append(task_id)
                    continue

            if self.complete(task_id):
                results["acknowledged"].append(task_id)

        return results

    def fail(self, task_id: str, queue: str = "default") -> bool:
        """Mark a task as failed. Idempotent for already-completed tasks."""
        if task_id in self._completed:
            return False
        task = self._in_flight.pop(task_id, None)
        if task:
            worker_id = task.get("worker_id")
            if worker_id and worker_id in self._batch_owners:
                self._batch_owners[worker_id].discard(task_id)
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                task.pop("worker_id", None)
                task.pop("dequeued_at", None)
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def completed_count(self) -> int:
        return len(self._completed)

    def get_batch_owner(self, task_id: str) -> Optional[str]:
        task = self._in_flight.get(task_id)
        if task:
            return task.get("worker_id")
        return None
