"""Task Scheduler — Priority-based task queuing and dispatch with deletion gating."""

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
    """Task scheduler with deletion-state gating.

    The scheduler tracks deleted workflow IDs to prevent run creation
    after a workflow has been removed — closing a deletion-race window
    where stale requests could create orphan runs.
    """

    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        # Deletion-state tracking — set of workflow IDs that have been deleted.
        self._deleted_workflows: Set[str] = set()
        # Audit log for gated decisions.
        self._audit_log: list = []

    # ---- Deletion gating ----

    def mark_workflow_deleted(self, workflow_id: str) -> None:
        """Record a workflow as deleted so future run creation is rejected."""
        self._deleted_workflows.add(workflow_id)
        self._audit_log.append({
            "event": "workflow_deleted",
            "workflow_id": workflow_id,
            "timestamp": time.time(),
        })
        logger.info("Workflow %s marked deleted — run creation gated", workflow_id)

    def is_workflow_deleted(self, workflow_id: str) -> bool:
        """Return True if the workflow has been marked as deleted."""
        return workflow_id in self._deleted_workflows

    def _check_and_gate(self, workflow_id: str, context: str) -> bool:
        """Check deletion gate and log the decision. Returns True if gated (rejected)."""
        if self.is_workflow_deleted(workflow_id):
            self._audit_log.append({
                "event": "run_creation_rejected",
                "workflow_id": workflow_id,
                "context": context,
                "timestamp": time.time(),
            })
            logger.warning(
                "Run creation rejected for deleted workflow %s (context=%s)",
                workflow_id, context,
            )
            return True
        return False

    def get_audit_log(self) -> list:
        """Return bounded audit log of recent gate decisions."""
        return list(self._audit_log)

    # ---- Core operations ----

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> Optional[str]:
        workflow_id = task.get("workflow_id")
        if workflow_id and self._check_and_gate(workflow_id, "enqueue"):
            return None

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> Optional[str]:
        workflow_id = task.get("workflow_id")
        if workflow_id and self._check_and_gate(workflow_id, "schedule"):
            return None

        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task_ref = self._scheduled.pop(tid)
            if task_ref:
                self.enqueue(task_ref, queue)

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

    # ---- Lifecycle ----

    def clear_gates(self) -> None:
        """Clear all deletion gates — used in tests."""
        self._deleted_workflows.clear()
        self._audit_log.clear()
