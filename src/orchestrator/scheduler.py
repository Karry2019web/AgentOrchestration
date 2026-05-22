"""Task Scheduler — Priority-based task queuing and dispatch with workspace scoping."""

import heapq
import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from src.orchestrator.task_repository import TaskRepository


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
    """Task scheduler with workspace-scoped state enforcement.

    All task operations require a workspace_id to ensure tasks are
    scoped to their workspace. The scheduler delegates all persistent
    state to a TaskRepository instance.
    """

    def __init__(self, repository: Optional[TaskRepository] = None):
        self._repo = repository or TaskRepository()
        # Per-workspace priority queues (ephemeral ordering, not long-term state)
        self._queues: Dict[str, PriorityQueue] = {}
        self._max_retries = 3

    def enqueue(self, task: Dict, workspace_id: str, queue: str = "default", priority: int = 0) -> str:
        """Enqueue a task under a workspace scope.

        Args:
            task: Task payload dict.
            workspace_id: Scoping workspace identifier (required).
            queue: Queue name within the workspace.
            priority: Higher = dequeued sooner.

        Returns:
            The generated task ID.
        """
        task_id = str(uuid4())
        task["id"] = task_id
        task["workspace_id"] = workspace_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        # Persist in workspace-scoped repository
        self._repo.put_task(workspace_id, task_id, task)

        # Add to in-memory priority queue for this workspace
        queue_key = f"{workspace_id}:{queue}"
        if queue_key not in self._queues:
            self._queues[queue_key] = PriorityQueue()
        self._queues[queue_key].push(task_id, priority)

        return task_id

    def schedule(self, task: Dict, delay: float, workspace_id: str, queue: str = "default", priority: int = 0) -> str:
        """Schedule a future task under workspace scope.

        Args:
            task: Task payload dict.
            delay: Seconds from now to schedule the task for.
            workspace_id: Scoping workspace identifier (required).
            queue: Queue name within the workspace.
            priority: Higher = dequeued sooner.

        Returns:
            The generated task ID.
        """
        task_id = str(uuid4())
        task["id"] = task_id
        task["workspace_id"] = workspace_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        # Persist in workspace-scoped repository
        self._repo.put_task(workspace_id, task_id, task)
        self._repo.schedule_task(workspace_id, task_id, task, time.time() + delay)

        return task_id

    async def dequeue(self, workspace_id: str, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        """Dequeue the next task from a workspace queue.

        Args:
            workspace_id: Scoping workspace identifier (required).
            queue: Queue name within the workspace.
            timeout: Unused in this implementation; kept for API compatibility.

        Returns:
            The next task, or None if the queue is empty.
        """
        # Move expired scheduled tasks to the active queue
        now = time.time()
        expired = self._repo.list_expired_scheduled(workspace_id, now)
        for tid, task in expired:
            queue_key = f"{workspace_id}:{queue}"
            if queue_key not in self._queues:
                self._queues[queue_key] = PriorityQueue()
            self._queues[queue_key].push(tid, task.get("priority", 0))

        # Dequeue from priority queue
        queue_key = f"{workspace_id}:{queue}"
        if queue_key in self._queues and len(self._queues[queue_key]) > 0:
            task_id = self._queues[queue_key].pop()
            if task_id:
                task = self._repo.get_task(workspace_id, task_id)
                if task:
                    self._repo.mark_in_flight(workspace_id, task_id, task)
                    return task
        return None

    def get_task(self, workspace_id: str, task_id: str) -> Optional[Dict]:
        """Retrieve a workspace-scoped task by ID."""
        return self._repo.get_task(workspace_id, task_id)

    def complete(self, task_id: str, workspace_id: str) -> bool:
        """Mark a task as completed under its workspace scope."""
        task = self._repo.complete_in_flight(workspace_id, task_id)
        if task is None:
            return False
        self._repo.delete_task(workspace_id, task_id)
        return True

    def fail(self, task_id: str, workspace_id: str, queue: str = "default") -> bool:
        """Retry a failed task under its workspace scope.

        Returns True if the task was retried, False if max retries exceeded.
        """
        task = self._repo.complete_in_flight(workspace_id, task_id)
        if task is None:
            return False
        task["retries"] += 1
        if task["retries"] < self._max_retries:
            self._repo.put_task(workspace_id, task_id, task)
            queue_key = f"{workspace_id}:{queue}"
            if queue_key not in self._queues:
                self._queues[queue_key] = PriorityQueue()
            self._queues[queue_key].push(task_id, task.get("priority", 0))
            return True
        return False

    def get_repository(self) -> TaskRepository:
        """Expose the underlying repository for audit/inspection."""
        return self._repo
