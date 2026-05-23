"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import time
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class VisibilityTimeoutError(Exception):
    """Raised when a task's visibility deadline has expired."""
    pass


class VisibilityTimeoutManager:
    """Manages visibility timeouts for in-flight tasks.

    Each dequeued task gets a visibility deadline. The deadline can be
    extended for long-running agents. If a task's deadline expires before
    it is completed or failed, the task becomes eligible for re-delivery
    to another worker.
    """

    def __init__(self, default_timeout: float = 30.0, max_extensions: int = 10):
        self.default_timeout = default_timeout
        self.max_extensions = max_extensions
        self._deadlines: Dict[str, float] = {}
        self._extensions: Dict[str, int] = {}
        self._lease_holders: Dict[str, str] = {}

    def claim(self, task_id: str, worker_id: str, timeout: Optional[float] = None) -> float:
        """Claim a task with a fresh visibility deadline.

        Args:
            task_id: The task to claim.
            worker_id: The claiming worker.
            timeout: Visibility timeout in seconds (defaults to default_timeout).

        Returns:
            The deadline timestamp (Unix epoch seconds).
        """
        deadline = time.time() + (timeout or self.default_timeout)
        self._deadlines[task_id] = deadline
        self._extensions[task_id] = 0
        self._lease_holders[task_id] = worker_id
        logger.debug("Claimed task %s for worker %s until %.3f", task_id, worker_id, deadline)
        return deadline

    def extend(self, task_id: str, worker_id: str, extension: float = 30.0) -> float:
        """Extend the visibility deadline for a long-running agent.

        Args:
            task_id: The task to extend.
            worker_id: The worker requesting the extension.
            extension: Additional seconds to extend (default 30s).

        Returns:
            The new deadline timestamp.

        Raises:
            VisibilityTimeoutError: If the task's deadline has already expired
                or the worker does not hold the lease.
        """
        self._check_lease(task_id, worker_id)
        if self._extensions.get(task_id, 0) >= self.max_extensions:
            logger.warning("Task %s has reached max extensions (%d)", task_id, self.max_extensions)
        self._extensions[task_id] = self._extensions.get(task_id, 0) + 1
        new_deadline = time.time() + extension
        self._deadlines[task_id] = new_deadline
        logger.debug(
            "Extended visibility for task %s to %.3f (extension %d/%d)",
            task_id, new_deadline, self._extensions[task_id], self.max_extensions,
        )
        return new_deadline

    def is_expired(self, task_id: str) -> bool:
        """Check if a task's visibility deadline has passed."""
        deadline = self._deadlines.get(task_id)
        if deadline is None:
            return True
        return time.time() > deadline

    def release(self, task_id: str, worker_id: str) -> None:
        """Release a claimed task (on complete or fail).

        Args:
            task_id: The task to release.
            worker_id: The worker releasing it.

        Raises:
            VisibilityTimeoutError: If the worker does not hold the lease.
        """
        self._check_lease(task_id, worker_id)
        self._deadlines.pop(task_id, None)
        self._extensions.pop(task_id, None)
        self._lease_holders.pop(task_id, None)

    def get_worker(self, task_id: str) -> Optional[str]:
        """Return the worker that currently holds the lease for a task."""
        return self._lease_holders.get(task_id)

    def get_deadline(self, task_id: str) -> Optional[float]:
        """Return the remaining deadline for the task."""
        return self._deadlines.get(task_id)

    def sweep_expired(self) -> list:
        """Return all task IDs whose visibility deadlines have expired.

        The caller should re-enqueue these tasks for re-delivery.
        """
        expired = [tid for tid, deadline in self._deadlines.items() if time.time() > deadline]
        for tid in expired:
            logger.info("Sweeping expired task %s for re-delivery", tid)
            self._deadlines.pop(tid, None)
            self._extensions.pop(tid, None)
            self._lease_holders.pop(tid, None)
        return expired

    def _check_lease(self, task_id: str, worker_id: str) -> None:
        holder = self._lease_holders.get(task_id)
        if holder is None:
            raise VisibilityTimeoutError(
                f"Task {task_id} has no lease holder — it may have been re-claimed"
            )
        if holder != worker_id:
            raise VisibilityTimeoutError(
                f"Task {task_id} is leased by worker {holder}, not {worker_id}"
            )
        if self.is_expired(task_id):
            raise VisibilityTimeoutError(
                f"Task {task_id} visibility deadline has expired"
            )


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
    def __init__(self, default_visibility_timeout: float = 30.0, max_visibility_extensions: int = 10):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._worker_id = str(uuid4())
        self._visibility = VisibilityTimeoutManager(
            default_timeout=default_visibility_timeout,
            max_extensions=max_visibility_extensions,
        )

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        logger.debug("Enqueued task %s on queue %s with priority %d", task_id, queue, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        logger.debug("Scheduled task %s with delay %.2fs on queue %s", task_id, delay, queue)
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
                self._visibility.claim(task["id"], self._worker_id, timeout=timeout)
                logger.debug("Dequeued task %s from queue %s", task["id"], queue)
                return task
        return None

    def extend_visibility(self, task_id: str, extension: float = 30.0) -> float:
        """Extend the visibility timeout for a long-running task.

        This allows long-running agents to keep processing without the
        task being re-delivered to another worker.
        """
        return self._visibility.extend(task_id, self._worker_id, extension)

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            self._visibility.release(task_id, self._worker_id)
            logger.debug("Completed task %s", task_id)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                self._visibility.release(task_id, self._worker_id)
                logger.debug("Failed task %s (retry %d/%d), re-enqueued", task_id, task["retries"], self._max_retries)
                return True
            else:
                self._visibility.release(task_id, self._worker_id)
                logger.warning("Task %s failed after %d retries, discarded", task_id, self._max_retries)
        return False

    def get_in_flight_count(self) -> int:
        return len(self._in_flight)

    def get_visibility(self) -> VisibilityTimeoutManager:
        return self._visibility
