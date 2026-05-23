"""Tests for workspace-scoped task state storage."""

import pytest
from src.common.storage import WorkspaceScopedTaskStore


class TestWorkspaceScopedTaskStore:
    """Verify row-level workspace scope enforcement in task state storage."""

    def setup_method(self):
        self.store = WorkspaceScopedTaskStore()

    def test_put_and_get_within_workspace(self):
        """A task stored in workspace-A should be retrievable from workspace-A."""
        self.store.put("workspace-a", "task-1", {"name": "test-task"})
        result = self.store.get("workspace-a", "task-1")
        assert result is not None
        assert result["name"] == "test-task"
        assert result["workspace_id"] == "workspace-a"

    def test_cannot_read_other_workspace(self):
        """A task stored in workspace-A should NOT be visible from workspace-B."""
        self.store.put("workspace-a", "task-1", {"name": "secret"})
        result = self.store.get("workspace-b", "task-1")
        assert result is None

    def test_task_id_collision_across_workspaces(self):
        """Identical task IDs in different workspaces should not conflict."""
        self.store.put("workspace-a", "task-1", {"name": "alpha"})
        self.store.put("workspace-b", "task-1", {"name": "beta"})

        a_result = self.store.get("workspace-a", "task-1")
        b_result = self.store.get("workspace-b", "task-1")

        assert a_result["name"] == "alpha"
        assert b_result["name"] == "beta"

    def test_cross_workspace_collision_detection(self):
        """find_task_across_workspaces should discover the same task ID in
        multiple workspaces."""
        self.store.put("workspace-a", "shared-id", {"name": "first"})
        self.store.put("workspace-b", "shared-id", {"name": "second"})

        results = self.store.find_task_across_workspaces("shared-id")
        assert len(results) == 2
        ws_ids = {r[0] for r in results}
        assert ws_ids == {"workspace-a", "workspace-b"}

    def test_delete_within_workspace(self):
        """Deleting a task in workspace-A should not affect workspace-B."""
        self.store.put("workspace-a", "task-1", {"name": "alpha"})
        self.store.put("workspace-b", "task-1", {"name": "beta"})

        assert self.store.delete("workspace-a", "task-1") is True
        assert self.store.get("workspace-a", "task-1") is None
        # workspace-B should still have it
        assert self.store.get("workspace-b", "task-1") is not None

    def test_list_by_workspace(self):
        """listing tasks should only return tasks for the given workspace."""
        self.store.put("workspace-a", "t1", {"name": "a1"})
        self.store.put("workspace-a", "t2", {"name": "a2"})
        self.store.put("workspace-b", "t3", {"name": "b1"})

        a_tasks = self.store.list_by_workspace("workspace-a")
        assert len(a_tasks) == 2

        b_tasks = self.store.list_by_workspace("workspace-b")
        assert len(b_tasks) == 1

    def test_find_by_status_scoped(self):
        """Finding by status should respect workspace boundaries."""
        self.store.put("ws-1", "t1", {"status": "running"})
        self.store.put("ws-1", "t2", {"status": "completed"})
        self.store.put("ws-2", "t3", {"status": "running"})

        running_in_ws1 = self.store.find_by_status("ws-1", "running")
        assert len(running_in_ws1) == 1
        assert running_in_ws1[0]["task_id"] == "t1"

    def test_count_by_workspace(self):
        self.store.put("ws-1", "t1", {})
        self.store.put("ws-1", "t2", {})
        self.store.put("ws-2", "t3", {})
        assert self.store.count_by_workspace("ws-1") == 2
        assert self.store.count_by_workspace("ws-2") == 1
        assert self.store.count_by_workspace("ws-3") == 0

    def test_clear_workspace(self):
        self.store.put("ws-1", "t1", {})
        self.store.put("ws-1", "t2", {})
        assert self.store.clear_workspace("ws-1") == 2
        assert self.store.count_by_workspace("ws-1") == 0

    def test_empty_workspace_returns_none(self):
        assert self.store.get("nonexistent", "task-1") is None
        assert self.store.list_by_workspace("nonexistent") == []
        assert self.store.delete("nonexistent", "task-1") is False

    def test_put_raises_on_empty_workspace(self):
        with pytest.raises(ValueError, match="workspace_id is required"):
            self.store.put("", "task-1", {})

    def test_task_id_exists(self):
        self.store.put("ws-1", "task-1", {})
        assert self.store.task_id_exists("ws-1", "task-1") is True
        assert self.store.task_id_exists("ws-1", "nonexistent") is False
        assert self.store.task_id_exists("ws-2", "task-1") is False

# 2026-05-24T08:00:00 update
