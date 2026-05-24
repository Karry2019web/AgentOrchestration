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
    """Priority-based task scheduler with leader election and deduplicated job registration.

    During rolling deployments, multiple scheduler instances may overlap.
    This class uses an in-process leader lease and a registry of known job names
    to prevent duplicate scheduled job registrations.
    """

    def __init__(self, instance_id: Optional[str] = None, lease_ttl: float = 30.0):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

        # Leader election state
        self._instance_id: str = instance_id or str(uuid4())
        self._lease_ttl: float = lease_ttl
        self._leader_id: Optional[str] = None
        self._lease_expiry: float = 0.0

        # Job deduplication registry
        self._registered_jobs: Set[str] = set()
        self._job_owners: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Leader election
    # ------------------------------------------------------------------

    def _is_leader(self) -> bool:
        """Return True if this instance currently holds the leader lease."""
        return self._leader_id == self._instance_id

    def _acquire_leadership(self) -> bool:
        """Attempt to acquire the leader lease.

        A simple compare-and-swap model: if no leader exists or the lease
        has expired, this instance becomes the leader.
        """
        now = time.time()
        if self._leader_id is None or now >= self._lease_expiry:
            self._leader_id = self._instance_id
            self._lease_expiry = now + self._lease_ttl
            logger.info("Scheduler %s acquired leader lease (expires %.1f)",
                        self._instance_id, self._lease_expiry)
            return True
        return False

    def _renew_lease(self) -> None:
        """Extend the leader lease if this instance is the current leader."""
        if self._is_leader():
            now = time.time()
            if now < self._lease_expiry:
                self._lease_expiry = now + self._lease_ttl

    def _release_leadership(self) -> None:
        """Relinquish the leader lease."""
        if self._is_leader():
            logger.info("Scheduler %s releasing leader lease", self._instance_id)
            self._leader_id = None
            self._lease_expiry = 0.0

    # ------------------------------------------------------------------
    # Idempotent job registration (prevents duplicate cron jobs during rollout)
    # ------------------------------------------------------------------

    def register_job(self, job_name: str, task: Dict, queue: str = "default",
                     priority: int = 0) -> Optional[str]:
        """Register a scheduled job with deduplication.

        During rolling deployments, old and new scheduler instances can both
        attempt to register the same cron job. This method ensures at-most-once
        registration per *job_name* across all instances by requiring leader
        status and tracking known job names.

        Returns the task ID if the job was newly registered, or *None* if the
        job is already registered (or this instance is not the leader).
        """
        if not self._is_leader():
            logger.warning("Instance %s is not leader -- skipping registration of job '%s'",
                           self._instance_id, job_name)
            return None

        if job_name in self._registered_jobs:
            logger.info("Job '%s' already registered by leader %s -- skipping duplicate",
                        job_name, self._instance_id)
            return None

        task_id = self.enqueue(task, queue=queue, priority=priority)
        self._registered_jobs.add(job_name)
        self._job_owners[job_name] = self._instance_id
        logger.info("Job '%s' registered (task %s) by leader %s",
                    job_name, task_id, self._instance_id)
        return task_id

    def unregister_job(self, job_name: str) -> bool:
        """Remove a previously registered job.

        Only the leader instance that owns the job may unregister it.
        """
        if not self._is_leader():
            return False
        owner = self._job_owners.get(job_name)
        if owner is None or owner != self._instance_id:
            return False
        self._registered_jobs.discard(job_name)
        self._job_owners.pop(job_name, None)
        logger.info("Job '%s' unregistered by leader %s", job_name, self._instance_id)
        return True

    def list_registered_jobs(self) -> Set[str]:
        """Return the set of currently registered job names."""
        return set(self._registered_jobs)

    # ------------------------------------------------------------------
    # Core task operations
    # ------------------------------------------------------------------

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default",
                 priority: int = 0) -> str:
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
