"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4


class BatchAckError(Exception):
    """Raised when batch acknowledgement ownership validation fails."""


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
        self._in_flight_by_worker: Dict[str, Set[str]] = {}
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

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                worker = worker_id or "default_worker"
                task["worker_id"] = worker
                if worker not in self._in_flight_by_worker:
                    self._in_flight_by_worker[worker] = set()
                self._in_flight_by_worker[worker].add(task["id"])
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            worker = task.get("worker_id")
            if worker and worker in self._in_flight_by_worker:
                self._in_flight_by_worker[worker].discard(task_id)
                if not self._in_flight_by_worker[worker]:
                    del self._in_flight_by_worker[worker]
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            worker = task.get("worker_id")
            if worker and worker in self._in_flight_by_worker:
                self._in_flight_by_worker[worker].discard(task_id)
                if not self._in_flight_by_worker[worker]:
                    del self._in_flight_by_worker[worker]
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def batch_acknowledge(self, task_ids: List[str], worker_id: str) -> Tuple[int, List[str]]:
        """Acknowledge multiple tasks atomically with worker ownership validation.

        Args:
            task_ids: List of task IDs to acknowledge.
            worker_id: The worker claiming ownership of these tasks.

        Returns:
            Tuple of (acknowledged_count, rejected_task_ids).

        Raises:
            BatchAckError: If the worker does not own any of the listed tasks.
        """
        if not task_ids:
            return 0, []

        owned = self._in_flight_by_worker.get(worker_id, set())
        if not owned:
            raise BatchAckError(
                f"Worker '{worker_id}' has no in-flight tasks to acknowledge"
            )

        acknowledged = 0
        rejected = []

        for tid in task_ids:
            if tid in owned:
                if self.complete(tid):
                    acknowledged += 1
                else:
                    rejected.append(tid)
            else:
                rejected.append(tid)

        return acknowledged, rejected
