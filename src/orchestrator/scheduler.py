"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
import logging
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class HealthStatus:
    """Tracks external service health for dependency-aware scheduling."""

    def __init__(self, name: str, check_interval: float = 30.0):
        self.name = name
        self.check_interval = check_interval
        self._healthy = True
        self._last_checked = 0.0
        self._consecutive_failures = 0
        self._max_failures = 3

    @property
    def is_healthy(self) -> bool:
        return self._healthy

    @property
    def is_stale(self) -> bool:
        return time.time() - self._last_checked > self.check_interval * 2

    def record_success(self) -> None:
        self._healthy = True
        self._consecutive_failures = 0
        self._last_checked = time.time()

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        self._last_checked = time.time()
        if self._consecutive_failures >= self._max_failures:
            self._healthy = False
            logger.warning(f"Health gate [{self.name}]: marked unhealthy after {self._consecutive_failures} consecutive failures")

    def reset(self) -> None:
        self._healthy = True
        self._consecutive_failures = 0
        self._last_checked = time.time()


class HealthGate:
    """Central health gate for external service dependency checks.

    Defer runs during dependency outages — runs are queued until the dependency
    recovers, preventing duplicated, delayed, or out-of-policy dispatch.
    """

    def __init__(self):
        self._services: Dict[str, HealthStatus] = {}
        self._defers: Dict[str, List[Dict]] = {}

    def register(self, name: str, check_interval: float = 30.0) -> HealthStatus:
        status = HealthStatus(name, check_interval)
        self._services[name] = status
        self._defers[name] = []
        return status

    def get_status(self, name: str) -> Optional[HealthStatus]:
        return self._services.get(name)

    def check(self, name: str, probe: Callable[[], bool]) -> bool:
        """Execute a health probe and record the result.
        
        Returns True if the service is healthy after the probe, False otherwise.
        """
        status = self._services.get(name)
        if status is None:
            return True  # Unknown services are assumed healthy
        try:
            result = probe()
            if result:
                status.record_success()
            else:
                status.record_failure()
        except Exception as e:
            logger.error(f"Health gate probe [{name}] failed with exception: {e}")
            status.record_failure()
            return False
        return status.is_healthy

    def can_schedule(self, name: str) -> bool:
        """Check if scheduling is allowed for the given dependency.
        
        Atomic state precondition applied before committing scheduling,
        routing, queue, or workflow state.
        """
        status = self._services.get(name)
        if status is None:
            return True
        return status.is_healthy and not status.is_stale

    def defer(self, task: Dict, name: str, reason: str = "dependency_unhealthy") -> str:
        """Defer a run during dependency outage."""
        task_id = task.get("id", str(uuid4()))
        self._defers.setdefault(name, []).append({
            "task_id": task_id,
            "task": task,
            "deferred_at": time.time(),
            "reason": reason,
        })
        logger.info(f"Deferred task {task_id} due to {name} outage: {reason}")
        return task_id

    def release_deferred(self, name: str) -> List[Dict]:
        """Release all deferred tasks for a now-healthy dependency."""
        tasks = self._defers.pop(name, [])
        if tasks:
            logger.info(f"Released {len(tasks)} deferred tasks for {name}")
        return [t["task"] for t in tasks]

    def all_unhealthy(self) -> List[str]:
        return [name for name, s in self._services.items() if not s.is_healthy]

    def count_deferred(self) -> int:
        return sum(len(tasks) for tasks in self._defers.values())


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
        self.health_gate = HealthGate()

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

# 2019-04-25T08:37:12 update

# 2019-06-04T16:40:00 update

# 2019-07-11T12:01:28 update

# 2019-08-02T12:20:21 update

# 2019-08-23T10:38:50 update

# 2019-10-31T13:55:52 update

# 2019-11-04T20:12:32 update

# 2019-12-13T12:22:36 update

# 2020-02-01T10:32:37 update

# 2020-02-26T09:44:38 update

# 2020-03-09T19:00:55 update

# 2020-05-01T18:40:34 update

# 2020-05-12T15:10:31 update

# 2020-06-30T13:24:19 update

# 2020-09-22T16:00:45 update

# 2020-10-20T10:52:48 update

# 2020-10-21T12:18:08 update

# 2020-11-06T12:35:01 update

# 2020-12-09T08:09:33 update

# 2021-01-07T08:20:36 update

# 2021-10-02T15:23:16 update

# 2021-10-06T16:14:57 update

# 2021-10-06T09:27:41 update

# 2021-11-19T08:37:40 update

# 2022-03-01T16:39:54 update

# 2022-05-26T13:43:07 update

# 2022-06-02T10:50:58 update

# 2022-06-14T10:46:48 update

# 2022-07-31T16:44:34 update

# 2022-08-30T18:20:12 update

# 2022-11-04T14:47:03 update

# 2022-12-06T10:36:49 update

# 2022-12-22T13:21:12 update

# 2022-12-26T12:24:50 update

# 2023-03-09T08:09:55 update

# 2023-05-01T10:07:37 update

# 2023-06-08T14:32:15 update

# 2023-07-14T17:24:18 update

# 2023-12-14T08:38:31 update

# 2024-02-20T13:43:58 update

# 2024-03-24T08:52:42 update

# 2024-03-28T15:27:17 update

# 2024-03-29T18:10:33 update

# 2024-04-15T20:18:31 update

# 2024-05-27T13:11:52 update

# 2024-05-27T16:42:56 update

# 2024-06-20T13:03:45 update

# 2024-06-28T12:32:58 update

# 2024-07-10T14:10:16 update

# 2024-07-26T14:18:59 update

# 2024-08-12T08:21:05 update

# 2024-08-21T16:58:40 update

# 2024-09-27T19:54:30 update

# 2024-10-21T13:47:42 update

# 2024-11-11T09:19:27 update

# 2024-12-24T08:23:41 update

# 2025-02-14T10:35:15 update

# 2025-03-31T18:09:40 update

# 2025-06-21T17:32:49 update

# 2025-07-21T16:52:28 update

# 2025-08-20T19:45:16 update

# 2025-11-04T18:54:24 update

# 2025-12-09T20:17:36 update

# 2026-01-12T15:42:32 update

# 2026-01-23T14:41:20 update

# 2026-03-18T14:43:07 update

# 2026-04-13T11:43:19 update

