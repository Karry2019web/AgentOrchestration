"""Workspace-scoped task state storage — enforces row-level workspace scope.

This module provides a scoped task state repository that enforces workspace
isolation at the data access layer. Every read and write requires a workspace
scope, preventing cross-tenant data leaks.
"""

import time
import logging
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


class WorkspaceScopedTaskStore:
    """In-memory task state store that enforces workspace scope on all operations.

    This simulates a database with row-level security (RLS). Every record
    carries a workspace_id, and all queries filter by workspace_id.
    Direct unscoped access methods are intentionally absent — callers must
    always provide a workspace scope.
    """

    def __init__(self):
        # Nested dict: workspace_id -> { task_id -> task_record }
        self._data: Dict[str, Dict[str, dict]] = {}

    # ----- Scoped write operations -----

    def put(self, workspace_id: str, task_id: str, task_data: dict) -> None:
        """Store a task record scoped to a workspace.

        Raises ValueError if workspace_id is empty.
        """
        if not workspace_id:
            raise ValueError("workspace_id is required")
        if workspace_id not in self._data:
            self._data[workspace_id] = {}
        self._data[workspace_id][task_id] = {
            **task_data,
            "workspace_id": workspace_id,
            "task_id": task_id,
            "updated_at": time.time(),
        }

    def delete(self, workspace_id: str, task_id: str) -> bool:
        """Delete a task record within a workspace scope. Returns True if found."""
        if workspace_id not in self._data:
            return False
        return self._data[workspace_id].pop(task_id, None) is not None

    # ----- Scoped read operations -----

    def get(self, workspace_id: str, task_id: str) -> Optional[dict]:
        """Get a task record, scoped to workspace. Returns None if not found."""
        if workspace_id not in self._data:
            return None
        return self._data[workspace_id].get(task_id)

    def list_by_workspace(self, workspace_id: str) -> List[dict]:
        """List all task records for a workspace."""
        if workspace_id not in self._data:
            return []
        return list(self._data[workspace_id].values())

    def find_by_status(self, workspace_id: str, status: str) -> List[dict]:
        """Find task records in a workspace matching the given status."""
        if workspace_id not in self._data:
            return []
        return [
            r for r in self._data[workspace_id].values()
            if r.get("status") == status
        ]

    # ----- Cross-workspace collision detection -----

    def task_id_exists(self, workspace_id: str, task_id: str) -> bool:
        """Check if a task ID exists within the given workspace."""
        if workspace_id not in self._data:
            return False
        return task_id in self._data[workspace_id]

    def find_task_across_workspaces(self, task_id: str) -> List[Tuple[str, dict]]:
        """Find a task ID across all workspaces (for collision detection only).

        This is intentionally the only cross-workspace query and returns
        workspace context alongside the record so the caller can validate
        ownership.
        """
        results: List[Tuple[str, dict]] = []
        for ws_id, tasks in self._data.items():
            if task_id in tasks:
                results.append((ws_id, tasks[task_id]))
        return results

    def count_by_workspace(self, workspace_id: str) -> int:
        """Count task records for a workspace."""
        if workspace_id not in self._data:
            return 0
        return len(self._data[workspace_id])

    def clear_workspace(self, workspace_id: str) -> int:
        """Remove all tasks for a workspace. Returns count of removed items."""
        if workspace_id not in self._data:
            return 0
        count = len(self._data[workspace_id])
        del self._data[workspace_id]
        return count

# 2026-05-24T08:00:00 update
