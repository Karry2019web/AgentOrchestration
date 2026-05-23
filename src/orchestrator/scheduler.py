"""Task Scheduler - Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional
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
    """Scheduler with tenant-aware backlog burst prevention.

    When a paused tenant resumes, its accumulated backlog is released
    incrementally (up to *resume_batch_size* tasks per resume window)
    to avoid flooding the dispatch pipeline.
    """

    def __init__(self, resume_batch_size: int = 5, time_fn: Callable[[], float] = time.time):
        if resume_batch_size < 1:
            raise ValueError("resume_batch_size must be >= 1")
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._resume_batch_size = resume_batch_size
        self._time_fn = time_fn
        self._paused_tenants: Dict[str, str] = {}
        self._resume_windows: Dict[str, int] = {}
        self._resume_audit: List[Dict[str, Any]] = []
        self._audit_lock = threading.Lock()

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = self._time_fn()
        task["retries"] = 0
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = self._time_fn() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = self._time_fn()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)
        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                tenant = task.get("tenant_id", "")
                if tenant and tenant in self._paused_tenants:
                    self.enqueue(task, queue, 0)
                    return None
                self._in_flight[task["id"]] = task
                return task
        return None

    def pause_tenant(self, tenant_id: str, reason: str = "maintenance") -> bool:
        if not tenant_id:
            raise ValueError("tenant_id is required")
        self._paused_tenants[tenant_id] = reason
        self._resume_windows.pop(tenant_id, None)
        self._record_audit("pause", tenant_id=tenant_id, reason=reason)
        return True

    def resume_tenant(self, tenant_id: str) -> bool:
        if tenant_id not in self._paused_tenants:
            return False
        reason = self._paused_tenants.pop(tenant_id)
        self._resume_windows[tenant_id] = 0
        self._record_audit("resume", tenant_id=tenant_id, reason=reason)
        return True

    def dequeue_with_tenant_gate(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        task = asyncio.run(self.dequeue(queue, timeout))
        if task is None:
            return None
        tenant = task.get("tenant_id", "")
        if tenant and tenant in self._resume_windows:
            released = self._resume_windows.get(tenant, 0)
            if released >= self._resume_batch_size:
                self.enqueue(task, queue)
                self._record_audit("defer_resume_burst", tenant_id=tenant, reason=f"resume_window_exhausted")
                return None
            self._resume_windows[tenant] = released + 1
            self._record_audit("release_resumed", tenant_id=tenant, reason=f"batch_position={released + 1}")
        return task

    def advance_resume_window(self, tenant_id: str, batch_size: Optional[int] = None) -> bool:
        if tenant_id not in self._resume_windows:
            return False
        self._resume_windows[tenant_id] = 0
        if batch_size is not None:
            self._resume_batch_size = max(1, batch_size)
        self._record_audit("advance_window", tenant_id=tenant_id)
        return True

    def is_tenant_paused(self, tenant_id: str) -> bool:
        return tenant_id in self._paused_tenants

    def is_tenant_resuming(self, tenant_id: str) -> bool:
        return tenant_id in self._resume_windows

    @property
    def audit_events(self) -> List[Dict[str, Any]]:
        with self._audit_lock:
            return list(self._resume_audit)

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

    def _record_audit(self, action: str, **kwargs) -> None:
        with self._audit_lock:
            self._resume_audit.append({"action": action, "timestamp": self._time_fn(), **kwargs})
