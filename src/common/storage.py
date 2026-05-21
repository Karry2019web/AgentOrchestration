"""Storage Access Layer — Enforces workspace-scoped task state access."""

from typing import Any, Dict, List, Optional


class WorkspaceScopeError(Exception):
    """Raised when a storage operation lacks required workspace scope."""
    pass


class ScopedQueryError(Exception):
    """Raised when an unscoped query helper is used."""
    pass


class TaskStateStore:
    """In-memory task state store with mandatory workspace scoping.

    All read and write operations require a workspace_id parameter.
    Unscoped query helpers raise ScopedQueryError to prevent accidental
    cross-workspace data access.
    """

    def __init__(self):
        self._data: Dict[str, Dict[str, Dict]] = {}  # workspace_id -> task_id -> state

    def put(self, workspace_id: str, task_id: str, state: Dict[str, Any]) -> None:
        """Store task state scoped to a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task state writes")
        if workspace_id not in self._data:
            self._data[workspace_id] = {}
        self._data[workspace_id][task_id] = state

    def get(self, workspace_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve task state scoped to a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task state reads")
        return self._data.get(workspace_id, {}).get(task_id)

    def delete(self, workspace_id: str, task_id: str) -> bool:
        """Delete task state scoped to a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task state deletes")
        if workspace_id in self._data and task_id in self._data[workspace_id]:
            del self._data[workspace_id][task_id]
            if not self._data[workspace_id]:
                del self._data[workspace_id]
            return True
        return False

    def list_workspace(self, workspace_id: str) -> List[Dict[str, Any]]:
        """List all task states within a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task state listing")
        return list(self._data.get(workspace_id, {}).values())

    def has_task(self, workspace_id: str, task_id: str) -> bool:
        """Check if a task exists within a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task existence checks")
        return workspace_id in self._data and task_id in self._data[workspace_id]

    def count_workspace(self, workspace_id: str) -> int:
        """Count tasks in a workspace."""
        if not workspace_id:
            raise WorkspaceScopeError("workspace_id is required for task counting")
        return len(self._data.get(workspace_id, {}))

    # --- Unscoped helpers blocked by static checks ---

    def _get_all(self) -> Dict[str, Dict[str, Dict]]:
        """Internal only. Not exposed as a public API."""
        return self._data

    def get_all_tasks(self) -> Dict[str, Dict[str, Dict]]:
        """BLOCKED: Unscoped query that exposes cross-workspace data.

        Raises ScopedQueryError to prevent accidental misuse.
        """
        raise ScopedQueryError(
            "get_all_tasks() is an unscoped query that bypasses workspace isolation. "
            "Use list_workspace(workspace_id) instead."
        )


class ScopedTaskRepository:
    """High-level scoped repository wrapping TaskStateStore.

    Provides workspace-aware operations for task lifecycle management.
    """

    def __init__(self, store: TaskStateStore):
        self._store = store

    def record_state(self, workspace_id: str, task_id: str, state: str, metadata: Optional[Dict] = None) -> None:
        """Record a task state transition scoped to workspace."""
        existing = self._store.get(workspace_id, task_id) or {}
        existing.update({
            "task_id": task_id,
            "workspace_id": workspace_id,
            "state": state,
            "metadata": metadata or {},
            "updated_at": __import__("time").time(),
        })
        self._store.put(workspace_id, task_id, existing)

    def get_task(self, workspace_id: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task state scoped to workspace."""
        return self._store.get(workspace_id, task_id)

    def delete_task(self, workspace_id: str, task_id: str) -> bool:
        """Delete task state scoped to workspace."""
        return self._store.delete(workspace_id, task_id)

    def list_workspace_tasks(self, workspace_id: str) -> List[Dict[str, Any]]:
        """List all tasks in a workspace."""
        return self._store.list_workspace(workspace_id)

    def count_tasks(self, workspace_id: str) -> int:
        """Count tasks in a workspace."""
        return self._store.count_workspace(workspace_id)

    def task_exists_in_workspace(self, workspace_id: str, task_id: str) -> bool:
        """Check task existence scoped to workspace."""
        return self._store.has_task(workspace_id, task_id)

    def task_id_collides_across_workspaces(self, task_id: str, workspace_a: str, workspace_b: str) -> bool:
        """Check if the same task ID exists in different workspaces.

        This is a controlled cross-workspace query used for testing
        isolation guarantees.
        """
        return (
            self._store.has_task(workspace_a, task_id) and
            self._store.has_task(workspace_b, task_id)
        )
