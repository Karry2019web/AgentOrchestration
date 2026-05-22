"""
Task Repository — Workspace-scoped storage for task state.

Provides workspace-enforced read/write access to task state.
Every operation requires a workspace_id to prevent cross-workspace
data leakage. Direct unscoped access to internal data structures
is blocked in favor of these scoped methods.
"""

import time
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


class WorkspaceScopeError(PermissionError):
    """Raised when a task operation lacks or violates workspace scope."""

    def __init__(self, task_id: str, expected_workspace: str, actual_workspace: Optional[str] = None):
        message = f"Task {task_id} requires workspace scope '{expected_workspace}'"
        if actual_workspace is not None:
            message += f" but was accessed with '{actual_workspace}'"
        super().__init__(message)
        self.task_id = task_id
        self.expected_workspace = expected_workspace
        self.actual_workspace = actual_workspace


class TaskRepository:
    """In-memory task state store with workspace-scoped access enforcement.

    All read/write operations require a workspace_id parameter.
    Tasks are indexed by (workspace_id, task_id) to support identical
    task IDs across different workspaces.

    TODO: Replace in-memory storage with a database-backed implementation
    (e.g. PostgreSQL with RLS) for production use.
    """

    def __init__(self):
        self._tasks: Dict[str, Dict[str, Dict]] = {}
        self._in_flight: Dict[str, Dict[str, Dict]] = {}
        self._scheduled: Dict[str, Dict[str, Tuple[float, Dict]]] = {}

    # ---- Scoped query helpers ----

    def get_task(self, workspace_id: str, task_id: str) -> Optional[Dict]:
        """Retrieve a task by workspace-scoped ID."""
        workspace_tasks = self._tasks.get(workspace_id)
        if workspace_tasks is None:
            return None
        return workspace_tasks.get(task_id)

    def put_task(self, workspace_id: str, task_id: str, task: Dict) -> None:
        """Store a task under its workspace scope."""
        if workspace_id not in self._tasks:
            self._tasks[workspace_id] = {}
        task["_workspace_id"] = workspace_id
        self._tasks[workspace_id][task_id] = task

    def delete_task(self, workspace_id: str, task_id: str) -> bool:
        """Remove a task from its workspace. Returns True if removed."""
        workspace_tasks = self._tasks.get(workspace_id)
        if workspace_tasks and task_id in workspace_tasks:
            del workspace_tasks[task_id]
            return True
        return False

    def list_tasks(self, workspace_id: str) -> List[Dict]:
        """Return all tasks for a given workspace."""
        return list(self._tasks.get(workspace_id, {}).values())

    # ---- In-flight task management ----

    def mark_in_flight(self, workspace_id: str, task_id: str, task: Dict) -> None:
        """Mark a task as in-flight under workspace scope."""
        if workspace_id not in self._in_flight:
            self._in_flight[workspace_id] = {}
        task["_workspace_id"] = workspace_id
        self._in_flight[workspace_id][task_id] = task

    def get_in_flight(self, workspace_id: str, task_id: str) -> Optional[Dict]:
        """Get an in-flight task by workspace-scoped ID."""
        ws_flight = self._in_flight.get(workspace_id)
        if ws_flight is None:
            return None
        return ws_flight.get(task_id)

    def complete_in_flight(self, workspace_id: str, task_id: str) -> Optional[Dict]:
        """Remove and return a completed in-flight task."""
        ws_flight = self._in_flight.get(workspace_id)
        if ws_flight:
            return ws_flight.pop(task_id, None)
        return None

    def list_in_flight(self, workspace_id: str) -> List[Dict]:
        """Return all in-flight tasks for a workspace."""
        return list(self._in_flight.get(workspace_id, {}).values())

    # ---- Scheduled task management ----

    def schedule_task(self, workspace_id: str, task_id: str, task: Dict, run_at: float) -> None:
        """Schedule a task to run at a specific time under workspace scope."""
        if workspace_id not in self._scheduled:
            self._scheduled[workspace_id] = {}
        self._scheduled[workspace_id][task_id] = (run_at, task)

    def pop_scheduled(self, workspace_id: str, task_id: str) -> Optional[Tuple[float, Dict]]:
        """Remove and return a scheduled task."""
        ws_sched = self._scheduled.get(workspace_id)
        if ws_sched:
            return ws_sched.pop(task_id, None)
        return None

    def list_expired_scheduled(self, workspace_id: str, now: float) -> List[Tuple[str, Dict]]:
        """Return all scheduled tasks whose run_at <= now for a workspace."""
        ws_sched = self._scheduled.get(workspace_id, {})
        expired = []
        for tid, (run_at, task) in list(ws_sched.items()):
            if run_at <= now:
                expired.append((tid, task))
        for tid, _ in expired:
            del ws_sched[tid]
        return expired

    def count_by_workspace(self, workspace_id: str) -> int:
        """Return tasks stored for a given workspace."""
        return len(self._tasks.get(workspace_id, {}))

    def assert_workspace_isolation(self, workspace_a: str, workspace_b: str) -> bool:
        """Verify that tasks from different workspaces don't share IDs."""
        tasks_a = set(self._tasks.get(workspace_a, {}).keys())
        tasks_b = set(self._tasks.get(workspace_b, {}).keys())
        return len(tasks_a & tasks_b) == 0
