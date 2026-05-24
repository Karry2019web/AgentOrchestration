"""Task Scheduler — Priority-based task queuing and dispatch with workflow deletion guard."""

import asyncio
import heapq
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkflowDeletedError(Exception):
    """Raised when attempting to create a run for a deleted workflow."""
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
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        # Workflow deletion guard state
        self._deleted_workflows: Set[str] = set()
        self._deleted_workflow_audit: Dict[str, float] = {}
        self._lock = threading.Lock()

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        with self._lock:
            # Atomic precondition: reject if the workflow is deleted
            workflow_id = task.get("workflow_id")
            if workflow_id and workflow_id in self._deleted_workflows:
                raise WorkflowDeletedError(
                    f"Cannot enqueue task for deleted workflow {workflow_id}"
                )

            if queue not in self._queues:
                self._queues[queue] = PriorityQueue()
            self._queues[queue].push(task, priority)

        logger.info(f"Enqueued task {task_id} to queue '{queue}' (workflow={workflow_id})")
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id

        with self._lock:
            # Atomic precondition: reject if the workflow is deleted
            workflow_id = task.get("workflow_id")
            if workflow_id and workflow_id in self._deleted_workflows:
                raise WorkflowDeletedError(
                    f"Cannot schedule task for deleted workflow {workflow_id}"
                )
            self._scheduled[task_id] = time.time() + delay

        logger.info(f"Scheduled task {task_id} with delay {delay}s (workflow={workflow_id})")
        return task_id

    def mark_workflow_deleted(self, workflow_id: str) -> None:
        """Marks a workflow as deleted so no new runs can be created for it."""
        with self._lock:
            self._deleted_workflows.add(workflow_id)
            self._deleted_workflow_audit[workflow_id] = time.time()
        logger.warning(f"Workflow {workflow_id} marked as deleted — new runs blocked")

    def is_workflow_deleted(self, workflow_id: str) -> bool:
        """Check if a workflow is marked as deleted."""
        with self._lock:
            return workflow_id in self._deleted_workflows

    def remove_workflow_deletion_marker(self, workflow_id: str) -> bool:
        """Remove a deletion marker (for reconciliation)."""
        with self._lock:
            existed = self._deleted_workflows.discard(workflow_id)
            self._deleted_workflow_audit.pop(workflow_id, None)
            if existed:
                logger.info(f"Removed deletion marker for workflow {workflow_id}")
            return existed

    def get_deleted_workflows(self) -> List[str]:
        """Return list of all marked-as-deleted workflow IDs."""
        with self._lock:
            return list(self._deleted_workflows)

    def get_deletion_audit(self) -> Dict[str, float]:
        """Return deletion timestamps for all deleted workflows."""
        with self._lock:
            return dict(self._deleted_workflow_audit)

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
