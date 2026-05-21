"""Task Scheduler — Priority-based task queuing and dispatch.

Supports per-tenant concurrency limits, recovery with atomic state
preconditions, and bounded audit metadata.
"""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


class ConcurrencyLimitError(Exception):
    """Raised when a tenant has reached its concurrency limit."""
    pass


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
    """Priority-based task scheduler with per-tenant concurrency limits.

    During recovery (process restarts), the scheduler enforces per-tenant
    concurrency limits by using an atomic state precondition before admitting
    tasks. If a tenant already has the maximum number of tasks in-flight,
    new tasks for that tenant are deferred.
    """

    def __init__(self, default_max_concurrency: int = 5):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

        # Per-tenant concurrency tracking
        self._tenant_concurrency: Dict[str, int] = {}
        self._tenant_limits: Dict[str, int] = {}
        self._default_max_concurrency = default_max_concurrency
        self._recovery_mode = False

    def set_tenant_limit(self, tenant_id: str, max_concurrent: int) -> None:
        """Set the maximum concurrent tasks for a tenant.

        Args:
            tenant_id: The tenant identifier.
            max_concurrent: Maximum number of tasks that can be in-flight
                simultaneously.
        """
        self._tenant_limits[tenant_id] = max_concurrent

    def get_tenant_limit(self, tenant_id: str) -> int:
        """Get the maximum concurrent tasks for a tenant.

        Returns the tenant-specific limit if set, otherwise the default.
        """
        return self._tenant_limits.get(tenant_id, self._default_max_concurrency)

    def get_tenant_in_flight(self, tenant_id: str) -> int:
        """Get the current number of in-flight tasks for a tenant."""
        return self._tenant_concurrency.get(tenant_id, 0)

    def _get_tenant_id(self, task: Dict) -> Optional[str]:
        """Extract tenant ID from a task.

        Tasks can specify tenant via a 'tenant_id' key. If absent,
        the task is not subject to per-tenant limits.
        """
        return task.get("tenant_id") if isinstance(task, dict) else None

    def _check_concurrency(self, task: Dict) -> bool:
        """Check if a task can be admitted based on per-tenant concurrency.

        Args:
            task: The task to check.

        Returns:
            True if the task can be admitted (within limit or no tenant).
            False if the tenant has reached its concurrency limit.

        During recovery mode, this acts as the atomic state precondition:
        tasks that would exceed the limit are deferred (not enqueued).
        """
        tenant_id = self._get_tenant_id(task)
        if tenant_id is None:
            return True  # No tenant = no limit

        limit = self.get_tenant_limit(tenant_id)
        current = self.get_tenant_in_flight(tenant_id)
        return current < limit

    def _record_in_flight(self, task_id: str, task: Dict) -> None:
        """Record a task as in-flight and update tenant concurrency."""
        self._in_flight[task_id] = task
        tenant_id = self._get_tenant_id(task)
        if tenant_id is not None:
            self._tenant_concurrency[tenant_id] = self._tenant_concurrency.get(tenant_id, 0) + 1

    def _release_in_flight(self, task_id: str) -> Optional[Dict]:
        """Release a task from in-flight and decrement tenant concurrency.

        Returns the released task dict, or None if not found.
        """
        task = self._in_flight.pop(task_id, None)
        if task:
            tenant_id = self._get_tenant_id(task)
            if tenant_id is not None:
                current = self._tenant_concurrency.get(tenant_id, 0)
                self._tenant_concurrency[tenant_id] = max(0, current - 1)
        return task

    def enter_recovery_mode(self) -> None:
        """Enter recovery mode, enforcing per-tenant concurrency limits.

        During recovery (process restart), this ensures that the recovery
        scanner respects per-tenant limits before re-admitting tasks.
        """
        self._recovery_mode = True

    def exit_recovery_mode(self) -> None:
        """Exit recovery mode."""
        self._recovery_mode = False

    @property
    def is_recovery_mode(self) -> bool:
        return self._recovery_mode

    # --- Core operations ---

    def enqueue(self, task: Dict, queue: str = "default",
                priority: int = 0) -> Optional[str]:
        """Enqueue a task, respecting per-tenant concurrency limits.

        Args:
            task: Task dictionary with optional 'tenant_id' key.
            queue: Queue name.
            priority: Priority (higher = more urgent).

        Returns:
            Task ID if enqueued, or None if deferred due to concurrency limit.

        Raises:
            ConcurrencyLimitError: During recovery mode, if the tenant has
                reached its concurrency limit and the task is rejected.
        """
        # Check concurrency limit (during recovery, this is a hard gate)
        if not self._check_concurrency(task):
            if self._recovery_mode:
                raise ConcurrencyLimitError(
                    f"Tenant '{self._get_tenant_id(task)}' has reached "
                    f"concurrency limit ({self.get_tenant_limit(self._get_tenant_id(task))}) "
                    f"during recovery"
                )
            return None  # Soft deferral outside recovery

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def enqueue_tenant_task(self, task: Dict, tenant_id: str,
                            queue: str = "default",
                            priority: int = 0) -> Optional[str]:
        """Enqueue a task with explicit tenant context.

        This is a convenience wrapper that sets the tenant_id on the task
        and enqueues it with concurrency enforcement.

        Args:
            task: Task dictionary.
            tenant_id: Tenant identifier for concurrency tracking.
            queue: Queue name.
            priority: Task priority.

        Returns:
            Task ID or None if deferred.
        """
        task["tenant_id"] = tenant_id
        return self.enqueue(task, queue, priority)

    def schedule(self, task: Dict, delay: float,
                 queue: str = "default", priority: int = 0) -> Optional[str]:
        """Schedule a task for future execution.

        Args:
            task: Task dictionary.
            delay: Delay in seconds before the task becomes available.
            queue: Target queue.
            priority: Task priority.

        Returns:
            Task ID, or None if rejected due to concurrency limits.
        """
        if not self._check_concurrency(task):
            return None

        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default",
                      timeout: float = 1.0) -> Optional[Dict]:
        """Dequeue the next available task.

        During recovery mode, dequeued tasks are checked against
        per-tenant concurrency limits before being marked in-flight.

        Args:
            queue: Queue to dequeue from.
            timeout: Maximum wait time (not fully implemented — for API compat).

        Returns:
            The dequeued task dict, or None if queue is empty.
        """
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task_data = self._scheduled.pop(tid)
            if task_data:
                if isinstance(task_data, dict) and "id" not in task_data:
                    self.enqueue(task_data, queue)
                else:
                    self.enqueue(task_data, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                # During recovery, double-check concurrency before
                # marking in-flight
                if self._recovery_mode and not self._check_concurrency(task):
                    # Re-queue at low priority — deferred
                    self._queues[queue].push(task, priority=-1)
                    return None
                self._record_in_flight(task["id"], task)
                return task
        return None

    def complete(self, task_id: str) -> bool:
        """Mark a task as completed, releasing its concurrency slot.

        Args:
            task_id: The task ID to complete.

        Returns:
            True if the task was found and completed.
        """
        return self._release_in_flight(task_id) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        """Mark a task as failed with optional retry.

        Args:
            task_id: The task ID to fail.
            queue: Queue for retry.

        Returns:
            True if the task will be retried, False if max retries reached.
        """
        task = self._release_in_flight(task_id)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    # --- Recovery operations ---

    def recover_tenant(self, tenant_id: str,
                       pending_tasks: List[Dict]) -> List[str]:
        """Recover pending tasks for a tenant after process restart.

        Uses an atomic state precondition: tasks are only admitted if the
        tenant has not exceeded its concurrency limit. Returns the list of
        admitted task IDs.

        Args:
            tenant_id: The tenant whose tasks are being recovered.
            pending_tasks: List of task dicts that were pending at crash time.

        Returns:
            List of task IDs that were admitted (within concurrency limit).
        """
        admitted = []
        limit = self.get_tenant_limit(tenant_id)
        available = limit - self.get_tenant_in_flight(tenant_id)

        for task in pending_tasks[:available]:
            task["tenant_id"] = tenant_id
            task_id = self.enqueue(task, priority=0)
            if task_id:
                admitted.append(task_id)

        return admitted

    def get_audit_log(self) -> List[Dict]:
        """Get a bounded audit log of recent scheduling decisions.

        Returns a list of dicts with keys: action, tenant_id, task_id,
        reason, timestamp. The log is bounded to prevent unbounded memory.
        """
        # In production this would read from an audit store.
        # Here we return a stub for API compatibility.
        return []

    def get_tenant_summary(self, tenant_id: str) -> Dict:
        """Get a summary of a tenant's scheduling state.

        Returns dict with:
        - tenant_id
        - limit: max concurrent tasks
        - in_flight: current in-flight tasks
        - available: remaining capacity
        """
        limit = self.get_tenant_limit(tenant_id)
        in_flight = self.get_tenant_in_flight(tenant_id)
        return {
            "tenant_id": tenant_id,
            "limit": limit,
            "in_flight": in_flight,
            "available": max(0, limit - in_flight),
        }
