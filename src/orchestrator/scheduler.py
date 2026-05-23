"""Task Scheduler — Priority-based task queuing and dispatch with lease management."""

import asyncio
import heapq
import logging
import time
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

DEFAULT_LEASE_TTL = 300
UPLOAD_LEASE_EXTENSION = 600


class TaskStatus(Enum):
    PENDING = "pending"
    IN_FLIGHT = "in_flight"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class Lease:
    """Tracks job lease with expiration and renewal."""

    def __init__(self, task_id: str, ttl: int = DEFAULT_LEASE_TTL):
        self.task_id = task_id
        self.ttl = ttl
        self.created_at = time.time()
        self.expires_at = time.time() + ttl
        self.renewals = 0

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def renew(self, extension: int = None) -> float:
        extension = extension or self.ttl
        self.expires_at = time.time() + extension
        self.renewals += 1
        return self.expires_at

    def remaining(self) -> float:
        return max(0.0, self.expires_at - time.time())


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
    def __init__(self, default_lease_ttl: int = DEFAULT_LEASE_TTL):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._leases: Dict[str, Lease] = {}
        self._uploading: Dict[str, Dict] = {}
        self._max_retries = 3
        self._default_lease_ttl = default_lease_ttl

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
                task_id = task["id"]
                self._in_flight[task_id] = task
                self._leases[task_id] = Lease(task_id, ttl=self._default_lease_ttl)
                return task
        return None

    def complete(self, task_id: str) -> bool:
        result = self._in_flight.pop(task_id, None) is not None
        self._leases.pop(task_id, None)
        self._uploading.pop(task_id, None)
        return result

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        self._leases.pop(task_id, None)
        self._uploading.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def mark_uploading(self, task_id: str) -> bool:
        if task_id not in self._in_flight:
            return False
        task = self._in_flight[task_id]
        self._uploading[task_id] = task
        lease = self._leases.get(task_id)
        if lease:
            lease.renew(UPLOAD_LEASE_EXTENSION)
            logger.info("Lease renewed for task %s (upload mode, TTL=%ds, renewals=%d)",
                        task_id, UPLOAD_LEASE_EXTENSION, lease.renewals)
        return True

    def renew_lease(self, task_id: str, extension: int = None) -> bool:
        if task_id not in self._in_flight:
            return False
        lease = self._leases.get(task_id)
        if lease:
            lease.renew(extension)
            return True
        return False

    def get_lease(self, task_id: str) -> Optional[Lease]:
        return self._leases.get(task_id)

    def is_uploading(self, task_id: str) -> bool:
        return task_id in self._uploading

    def finish_upload(self, task_id: str) -> bool:
        if task_id not in self._uploading:
            return False
        self._uploading.pop(task_id, None)
        lease = self._leases.get(task_id)
        if lease:
            lease.renew(self._default_lease_ttl)
        return True

    def recover_expired_leases(self) -> list:
        expired_ids = [
            tid for tid in self._in_flight
            if tid in self._leases and self._leases[tid].is_expired()
        ]
        recovered = []
        for tid in expired_ids:
            task = self._in_flight.pop(tid, None)
            self._leases.pop(tid, None)
            self._uploading.pop(tid, None)
            if task:
                logger.warning("Recovering expired task %s (lease expired)", tid)
                task["retries"] += 1
                task["recovered"] = True
                if task["retries"] < self._max_retries:
                    self.enqueue(task, "default", priority=0)
                    recovered.append(tid)
        return recovered

    def get_status(self, task_id: str) -> TaskStatus:
        if task_id in self._uploading:
            return TaskStatus.UPLOADING
        if task_id in self._in_flight:
            return TaskStatus.IN_FLIGHT
        return TaskStatus.PENDING
