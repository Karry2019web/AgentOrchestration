"""Task Scheduler — Priority-based task queuing and dispatch with workspace scope."""

import asyncio
import heapq
import time
import logging
from typing import Any, Dict, Optional
from uuid import uuid4

from src.common.storage import WorkspaceScopedTaskStore

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
    """Scheduler that enforces workspace scope on all task state operations."""

    def __init__(self, task_store: Optional[WorkspaceScopedTaskStore] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}  # task_id -> ready_at timestamp
        self._in_flight: Dict[str, Dict] = {}
        self._store = task_store or WorkspaceScopedTaskStore()
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0,
                workspace_id: str = "default") -> str:
        """Enqueue a task scoped to a workspace.

        The task record is persisted to the workspace-scoped store alongside
        the in-memory queue for later status lookups.
        """
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["status"] = "queued"
        task["workspace_id"] = workspace_id

        # Persist to workspace-scoped store
        self._store.put(workspace_id, task_id, task)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default",
                 priority: int = 0, workspace_id: str = "default") -> str:
        """Schedule a future task, scoped to a workspace."""
        task_id = str(uuid4())
        task["id"] = task_id
        task["workspace_id"] = workspace_id
        task["status"] = "scheduled"
        ready_at = time.time() + delay
        self._scheduled[task_id] = ready_at

        # Persist to workspace-scoped store
        self._store.put(workspace_id, task_id, task)
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task_data = self._scheduled.pop(tid, None)
            if task_data is not None:
                # task_data is just the timestamp, but we need the full task
                # Look it up from store by checking all workspaces
                pass

        # Handle expired scheduled tasks properly
        self._promote_expired()

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task["status"] = "in_flight"
                task["dequeued_at"] = time.time()
                self._in_flight[task["id"]] = task
                # Update status in store
                ws_id = task.get("workspace_id", "default")
                self._store.put(ws_id, task["id"], task)
                return task
        return None

    def _promote_expired(self) -> None:
        """Move expired scheduled tasks to their queues."""
        now = time.time()
        expired_ids = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired_ids:
            ready_at = self._scheduled.pop(tid, None)
            if ready_at is None:
                continue
            # Find the task in the store
            results = self._store.find_task_across_workspaces(tid)
            for ws_id, record in results:
                record["status"] = "queued"
                queue_name = record.get("queue", "default")
                if queue_name not in self._queues:
                    self._queues[queue_name] = PriorityQueue()
                self._queues[queue_name].push(record, record.get("priority", 0))
                break

    def complete(self, task_id: str, workspace_id: str = "default") -> bool:
        """Mark a task as completed within its workspace scope."""
        task = self._in_flight.pop(task_id, None)
        if task:
            task["status"] = "completed"
            task["completed_at"] = time.time()
            self._store.put(workspace_id, task_id, task)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default",
             workspace_id: str = "default") -> bool:
        """Mark a task as failed and optionally retry within scope."""
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            task["status"] = "failed"
            task["failed_at"] = time.time()
            if task["retries"] < self._max_retries:
                task["status"] = "queued"
                if queue not in self._queues:
                    self._queues[queue] = PriorityQueue()
                self._queues[queue].push(task, task.get("priority", 0))
            self._store.put(workspace_id, task_id, task)
            return True
        return False

    def get_task(self, task_id: str, workspace_id: str) -> Optional[Dict]:
        """Get task state, scoped to workspace. Returns None if not in workspace."""
        return self._store.get(workspace_id, task_id)

    def list_tasks(self, workspace_id: str) -> list:
        """List all tasks for a workspace."""
        return self._store.list_by_workspace(workspace_id)

    def get_queue_length(self, queue: str = "default") -> int:
        if queue in self._queues:
            return len(self._queues[queue])
        return 0

# 2026-05-24T08:00:00 update
