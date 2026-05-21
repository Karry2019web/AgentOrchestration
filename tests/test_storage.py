"""Tests for workspace-scoped task state access."""

import pytest
from src.common.storage import (
    TaskStateStore,
    ScopedTaskRepository,
    WorkspaceScopeError,
    ScopedQueryError,
)


class TestTaskStateStore:
    """Test the raw storage layer with workspace scoping."""

    def setup_method(self):
        self.store = TaskStateStore()

    def test_put_and_get_same_workspace(self):
        self.store.put("ws-1", "task-1", {"status": "running"})
        state = self.store.get("ws-1", "task-1")
        assert state is not None
        assert state["status"] == "running"

    def test_get_different_workspace_returns_none(self):
        """Task stored in ws-1 should not be visible in ws-2."""
        self.store.put("ws-1", "task-1", {"status": "running"})
        state = self.store.get("ws-2", "task-1")
        assert state is None

    def test_task_id_collision_across_workspaces(self):
        """Same task ID in different workspaces should be isolated."""
        self.store.put("ws-1", "task-1", {"status": "running"})
        self.store.put("ws-2", "task-1", {"status": "completed"})

        state1 = self.store.get("ws-1", "task-1")
        state2 = self.store.get("ws-2", "task-1")

        assert state1["status"] == "running"
        assert state2["status"] == "completed"
        assert state1 is not state2  # Different objects

    def test_delete_scoped(self):
        self.store.put("ws-1", "task-1", {"status": "running"})
        assert self.store.delete("ws-1", "task-1") is True
        assert self.store.get("ws-1", "task-1") is None

    def test_delete_nonexistent(self):
        assert self.store.delete("ws-1", "nonexistent") is False

    def test_delete_only_affects_one_workspace(self):
        self.store.put("ws-1", "task-1", {"status": "running"})
        self.store.put("ws-2", "task-1", {"status": "completed"})
        self.store.delete("ws-1", "task-1")

        assert self.store.get("ws-1", "task-1") is None
        assert self.store.get("ws-2", "task-1") is not None

    def test_list_workspace(self):
        self.store.put("ws-1", "task-1", {"status": "running"})
        self.store.put("ws-1", "task-2", {"status": "pending"})
        self.store.put("ws-2", "task-3", {"status": "completed"})

        tasks = self.store.list_workspace("ws-1")
        assert len(tasks) == 2
        assert all(t["status"] in ("running", "pending") for t in tasks)

    def test_has_task_scoped(self):
        self.store.put("ws-1", "task-1", {})
        assert self.store.has_task("ws-1", "task-1") is True
        assert self.store.has_task("ws-2", "task-1") is False

    def test_count_workspace(self):
        self.store.put("ws-1", "task-1", {})
        self.store.put("ws-1", "task-2", {})
        assert self.store.count_workspace("ws-1") == 2
        assert self.store.count_workspace("ws-2") == 0

    def test_put_without_workspace_raises(self):
        with pytest.raises(WorkspaceScopeError):
            self.store.put("", "task-1", {})

    def test_get_without_workspace_raises(self):
        with pytest.raises(WorkspaceScopeError):
            self.store.get("", "task-1")

    def test_unscoped_helper_blocked(self):
        with pytest.raises(ScopedQueryError):
            self.store.get_all_tasks()


class TestScopedTaskRepository:
    """Test high-level scoped repository."""

    def setup_method(self):
        self.store = TaskStateStore()
        self.repo = ScopedTaskRepository(self.store)

    def test_record_state(self):
        self.repo.record_state("ws-1", "task-1", "running", {"retry_count": 0})
        task = self.repo.get_task("ws-1", "task-1")
        assert task is not None
        assert task["state"] == "running"
        assert task["workspace_id"] == "ws-1"
        assert task["metadata"]["retry_count"] == 0

    def test_isolation_between_workspaces(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-2", "task-1", "completed")

        assert self.repo.get_task("ws-1", "task-1")["state"] == "running"
        assert self.repo.get_task("ws-2", "task-1")["state"] == "completed"

    def test_delete_task_scoped(self):
        self.repo.record_state("ws-1", "task-1", "running")
        assert self.repo.delete_task("ws-1", "task-1") is True
        assert self.repo.get_task("ws-1", "task-1") is None

    def test_list_workspace_tasks(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-1", "task-2", "completed")
        self.repo.record_state("ws-2", "task-3", "failed")

        ws1_tasks = self.repo.list_workspace_tasks("ws-1")
        assert len(ws1_tasks) == 2

        ws2_tasks = self.repo.list_workspace_tasks("ws-2")
        assert len(ws2_tasks) == 1

    def test_count_tasks(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-1", "task-2", "pending")
        assert self.repo.count_tasks("ws-1") == 2

    def test_task_exists_in_workspace(self):
        self.repo.record_state("ws-1", "task-1", "running")
        assert self.repo.task_exists_in_workspace("ws-1", "task-1") is True
        assert self.repo.task_exists_in_workspace("ws-2", "task-1") is False

    def test_task_id_collides_across_workspaces(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-2", "task-1", "completed")
        assert self.repo.task_id_collides_across_workspaces("task-1", "ws-1", "ws-2") is True
        assert self.repo.task_id_collides_across_workspaces("task-1", "ws-1", "ws-3") is False

    def test_record_state_updates_in_place(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-1", "task-1", "completed", {"reason": "success"})

        task = self.repo.get_task("ws-1", "task-1")
        assert task["state"] == "completed"
        assert task["metadata"]["reason"] == "success"
        assert "workspace_id" in task

    def test_scoped_delete_does_not_affect_other_workspaces(self):
        self.repo.record_state("ws-1", "task-1", "running")
        self.repo.record_state("ws-2", "task-1", "completed")
        self.repo.delete_task("ws-1", "task-1")

        assert self.repo.get_task("ws-1", "task-1") is None
        assert self.repo.get_task("ws-2", "task-1") is not None


class TestScopedQueryError:
    """Test that unscoped query helpers are blocked."""

    def test_get_all_tasks_raises(self):
        store = TaskStateStore()
        with pytest.raises(ScopedQueryError) as exc:
            store.get_all_tasks()
        assert "unscoped query" in str(exc.value).lower()
