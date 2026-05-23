"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import datetime
import hashlib
import heapq
import json
import logging
import time
from typing import Any, Dict, Optional, Set, Union
from uuid import uuid4

logger = logging.getLogger(__name__)


def _to_timestamp(when: Union[float, datetime.datetime]) -> float:
    """Convert a timezone-aware datetime or float delay to a Unix timestamp."""
    if isinstance(when, (int, float)):
        return time.time() + when
    if isinstance(when, datetime.datetime):
        if when.tzinfo is not None:
            when_utc = when.astimezone(datetime.timezone.utc)
            return when_utc.timestamp()
        else:
            return when.replace(tzinfo=datetime.timezone.utc).timestamp()
    raise TypeError(f"Unsupported schedule type: {type(when).__name__}")


def _job_hash(task: Dict) -> str:
    """Compute a deterministic hash for a scheduled job.

    Jobs with the same type and payload schedule are considered identical
    and deduplicated during rolling deployments.
    """
    key = {
        "type": task.get("type"),
        "payload": task.get("payload"),
        "queue": task.get("queue", "default"),
        "cron_expression": task.get("cron_expression"),
    }
    raw = json.dumps(key, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


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


class SchedulerLease:
    """Simple in-process lease for scheduler leader election.

    During rolling deployments, only the instance holding the lease
    registers and executes cron jobs. The lease is held for a TTL
    and must be refreshed periodically.
    """

    def __init__(self, instance_id: str, ttl: float = 30.0):
        self.instance_id = instance_id
        self.ttl = ttl
        self._acquired_at: Optional[float] = None

    @property
    def is_leader(self) -> bool:
        if self._acquired_at is None:
            return False
        return (time.time() - self._acquired_at) < self.ttl

    def acquire(self) -> bool:
        self._acquired_at = time.time()
        return True

    def release(self) -> None:
        self._acquired_at = None

    def refresh(self) -> None:
        if self._acquired_at is not None:
            self._acquired_at = time.time()


class TaskScheduler:
    def __init__(self, instance_id: Optional[str] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._registered_jobs: Set[str] = set()
        self.instance_id = instance_id or str(uuid4())[:8]
        self.lease = SchedulerLease(self.instance_id)

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
    ) -> Optional[str]:
        """Schedule a task for future execution.

        Returns None if a job with the same fingerprint is already registered
        (prevents duplicate cron jobs during rolling deployments).
        """
        task["queue"] = queue
        job_key = _job_hash(task)

        # Deduplicate: skip if same job already registered
        if job_key in self._registered_jobs:
            logger.debug(
                "Skipping duplicate job %s (already registered)",
                task.get("type", "unknown"),
            )
            return None

        self._registered_jobs.add(job_key)
        task_id = str(uuid4())
        task["id"] = task_id
        task["job_hash"] = job_key
        self._scheduled[task_id] = _to_timestamp(delay)
        return task_id

    def register_cron_job(self, task: Dict, interval: float, queue: str = "default") -> Optional[str]:
        """Register a recurring cron job with deduplication.

        During rolling deployments, only the leader instance registers jobs.
        Returns the task ID, or None if the job is a duplicate.
        """
        if not self.lease.is_leader:
            logger.info("Not leader — skipping cron job registration")
            return None

        task["cron_expression"] = f"every_{int(interval)}s"
        return self.schedule(task, interval, queue)

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task_data = self._scheduled.pop(tid)
            if task_data:
                self.enqueue(task_data, queue)

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
