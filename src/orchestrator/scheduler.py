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


class ScheduledJobRegistry:
    """Idempotent registry for scheduled jobs.

    During rolling deployments both old and new scheduler instances
    may attempt to register the same cron-based jobs. This registry
    ensures each job is registered at most once using a stable
    (job_name, schedule) composite key.
    """

    def __init__(self):
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._leader_id: Optional[str] = None

    def register_job(self, name: str, schedule: str, task: Dict) -> bool:
        """Register a scheduled job idempotently.

        Returns True if the job was newly registered, False if it
        was already registered (duplicate). Uses ``schedule:name``
        as the composite key so overlapping rollouts don't duplicate.
        """
        key = f"{schedule}:{name}"
        if key in self._jobs:
            logger.info(
                f"Scheduled job '{name}' ({schedule}) already registered — "
                f"skipping duplicate during rollout window"
            )
            return False

        self._jobs[key] = {
            "name": name,
            "schedule": schedule,
            "task": task,
            "registered_at": time.time(),
        }
        logger.info(f"Scheduled job '{name}' ({schedule}) registered")
        return True

    def unregister_job(self, name: str, schedule: str) -> bool:
        key = f"{schedule}:{name}"
        return self._jobs.pop(key, None) is not None

    def list_jobs(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._jobs)

    def claim_leadership(self, instance_id: str) -> bool:
        """Claim scheduler leadership for rollout deduplication.

        Returns True if this instance is now the leader. Only the
        leader executes cron-triggered jobs during overlapping rollouts.
        """
        if self._leader_id is None:
            self._leader_id = instance_id
            logger.info(f"Scheduler instance {instance_id} claimed leadership")
            return True
        return self._leader_id == instance_id

    def release_leadership(self, instance_id: str) -> None:
        if self._leader_id == instance_id:
            old = self._leader_id
            self._leader_id = None
            logger.info(f"Scheduler instance {old} released leadership")

    @property
    def is_leader(self) -> bool:
        return self._leader_id is not None

    def leader_instance_id(self) -> Optional[str]:
        return self._leader_id


class TaskScheduler:
    def __init__(self, instance_id: Optional[str] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._instance_id = instance_id or str(uuid4())[:8]
        self.job_registry = ScheduledJobRegistry()
        self._active_job_keys: Set[str] = set()

    @property
    def instance_id(self) -> str:
        return self._instance_id

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
        """Register a delayed task with deduplication.

        If a task with the same ``job_name`` key already exists in the
        schedule, it is treated as a duplicate and skipped.
        """
        job_name = task.get("job_name", task.get("id", str(uuid4())))
        schedule_key = f"delay:{queue}:{job_name}"

        if schedule_key in self._active_job_keys:
            logger.info(
                f"Scheduled job '{job_name}' already registered — "
                f"deduplicating during rollout"
            )
            return self._get_existing_task_id(job_name) or ""

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        self._scheduled[task_id] = time.time() + delay
        self._active_job_keys.add(schedule_key)
        return task_id

    def register_cron_job(self, name: str, schedule: str, task: Dict) -> bool:
        """Register a cron-based scheduled job with idempotency.

        During rolling deployments, only the first registration wins.
        Returns True if the job was newly registered.
        """
        return self.job_registry.register_job(name, schedule, task)

    def _get_existing_task_id(self, job_name: str) -> Optional[str]:
        for tid, task in self._in_flight.items():
            if task.get("job_name") == job_name or task.get("id") == job_name:
                return tid
        return None

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [(tid, t) for tid, t in self._scheduled.items() if t <= now]
        for tid, _ in expired:
            task = self._scheduled.pop(tid, None)
            if task:
                # Clean up the active job key for this task
                job_name = task.get("job_name", tid)
                schedule_key = f"delay:default:{job_name}"
                self._active_job_keys.discard(schedule_key)
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
