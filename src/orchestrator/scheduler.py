"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, Optional, Set
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
    """Priority-based task scheduler with reservation tracking and abandoned job reclamation.

    Features:
      - Priority queuing per named queue
      - Scheduled/delayed task support
      - Retry with configurable max attempts
      - Reservation tracking with lease expiry
      - Abandoned job reclamation on worker disconnect
    """

    def __init__(self, lease_expiry_seconds: float = 30.0):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._lease_expiry = lease_expiry_seconds
        # task_id -> {"worker_id": str, "reserved_at": float, "queue": str}
        self._reservations: Dict[str, Dict] = {}

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["queue"] = queue
        task["priority"] = priority

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0,
                      worker_id: Optional[str] = None) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task_id = task["id"]
                self._in_flight[task_id] = task
                # Track reservation so we can reclaim if worker disconnects
                self._reservations[task_id] = {
                    "worker_id": worker_id or "unknown",
                    "reserved_at": time.time(),
                    "queue": queue,
                }
                return task
        return None

    def complete(self, task_id: str) -> bool:
        self._reservations.pop(task_id, None)
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        self._reservations.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def reclaim_abandoned(self, worker_id: Optional[str] = None,
                          max_age: Optional[float] = None) -> int:
        """Requeue reservations that have been abandoned.

        When a worker disconnects, its in-flight reservations become stale.
        This method finds reservations whose lease has expired and moves them
        back to the ready queue so other workers can pick them up.

        Args:
            worker_id: If set, only reclaim jobs reserved by this worker.
                       If None, reclaim ALL expired reservations across workers.
            max_age: Override lease expiry check (defaults to self._lease_expiry).

        Returns:
            Number of tasks reclaimed.
        """
        if max_age is None:
            max_age = self._lease_expiry

        now = time.time()
        reclaimed = 0

        expired_ids = []
        for task_id, reservation in list(self._reservations.items()):
            age = now - reservation["reserved_at"]
            worker_match = worker_id is None or reservation["worker_id"] == worker_id
            if worker_match and age >= max_age:
                expired_ids.append(task_id)

        for task_id in expired_ids:
            reservation = self._reservations.pop(task_id, None)
            task = self._in_flight.pop(task_id, None)
            if task and reservation:
                original_queue = reservation.get("queue", "default")
                task["retries"] = task.get("retries", 0) + 1
                task["reclaimed_at"] = now
                task["reclaimed_from"] = reservation["worker_id"]
                if task["retries"] < self._max_retries:
                    prio = task.get("priority", 0)
                    self.enqueue(task, original_queue, priority=prio)
                    logger.info(
                        "Reclaimed abandoned task %s from worker %s -> queue %s (retry %d/%d)",
                        task_id, reservation["worker_id"], original_queue,
                        task["retries"], self._max_retries,
                    )
                else:
                    logger.warning(
                        "Dropping task %s — max retries (%d) exceeded after reclaim",
                        task_id, self._max_retries,
                    )
                reclaimed += 1

        return reclaimed

    @property
    def active_reservations(self) -> int:
        return len(self._reservations)

    @property
    def in_flight_count(self) -> int:
        return len(self._in_flight)

    def get_reservation(self, task_id: str) -> Optional[Dict]:
        return self._reservations.get(task_id)
