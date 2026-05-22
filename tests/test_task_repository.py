"""Tests for workspace-scoped TaskRepository."""

import pytest
from src.orchestrator.task_repository import TaskRepository, WorkspaceScopeError


class TestTaskRepository:
    """Tests for workspace scoping, isolation, and query helpers."""

    def setup_method(self):
        self.repo = TaskRepository()

    def test_put_and_get_task(self):
        """Tasks can be stored and retrieved by workspace."""
        self.repo.put_task("ws-1", "task-1", {"type": "test", "data": 1})
        task = self.repo.get_task("ws-1", "task-1")
        assert task is not None
        assert task["type"] == "test"

    def test_get_task_wrong_workspace(self):
        """Tasks are not visible across workspaces."""
        self.repo.put_task("ws-1", "task-1", {"type": "test"})
        task = self.repo.get_task("ws-2", "task-1")
        assert task is None

    def test_identical_task_ids_different_workspaces(self):
        """Same task ID in different workspaces are isolated."""
        self.repo.put_task("ws-a", "task-x", {"payload": "from-a"})
        self.repo.put_task("ws-b", "task-x", {"payload": "from-b"})

        task_a = self.repo.get_task("ws-a", "task-x")
        task_b = self.repo.get_task("ws-b", "task-x")

        assert task_a["payload"] == "from-a"
        assert task_b["payload"] == "from-b"
        # Each task should be tagged with its own workspace
        assert task_a["_workspace_id"] == "ws-a"
        assert task_b["_workspace_id"] == "ws-b"

    def test_delete_task(self):
        """Deleted tasks are removed and inaccessible."""
        self.repo.put_task("ws-1", "task-1", {"type": "test"})
        assert self.repo.delete_task("ws-1", "task-1") is True
        assert self.repo.get_task("ws-1", "task-1") is None

    def test_delete_nonexistent_task(self):
        """Deleting a non-existent task returns False."""
        assert self.repo.delete_task("ws-1", "no-such-task") is False

    def test_list_tasks_by_workspace(self):
        """Only tasks for the given workspace are listed."""
        self.repo.put_task("ws-1", "a", {"x": 1})
        self.repo.put_task("ws-1", "b", {"x": 2})
        self.repo.put_task("ws-2", "c", {"x": 3})

        ws1_tasks = self.repo.list_tasks("ws-1")
        ws2_tasks = self.repo.list_tasks("ws-2")

        assert len(ws1_tasks) == 2
        assert len(ws2_tasks) == 1

    def test_count_by_workspace(self):
        """Count is per-workspace."""
        self.repo.put_task("ws-1", "a", {})
        self.repo.put_task("ws-1", "b", {})
        assert self.repo.count_by_workspace("ws-1") == 2
        assert self.repo.count_by_workspace("ws-2") == 0

    def test_in_flight_lifecycle(self):
        """Task lifecycle: enqueue -> in_flight -> complete."""
        self.repo.put_task("ws-1", "t1", {"type": "test"})
        self.repo.mark_in_flight("ws-1", "t1", {"type": "test"})

        in_flight = self.repo.get_in_flight("ws-1", "t1")
        assert in_flight is not None

        completed = self.repo.complete_in_flight("ws-1", "t1")
        assert completed is not None

        assert self.repo.get_in_flight("ws-1", "t1") is None

    def test_in_flight_workspace_isolation(self):
        """In-flight tasks are isolated by workspace."""
        self.repo.mark_in_flight("ws-1", "t1", {"type": "a"})
        self.repo.mark_in_flight("ws-2", "t1", {"type": "b"})

        assert self.repo.get_in_flight("ws-1", "t1")["type"] == "a"
        assert self.repo.get_in_flight("ws-2", "t1")["type"] == "b"

    def test_schedule_and_expire(self):
        """Scheduled tasks are returned when their time arrives."""
        import time
        self.repo.put_task("ws-1", "sched1", {"type": "delayed"})
        self.repo.schedule_task("ws-1", "sched1", {"type": "delayed"}, time.time() - 1)

        expired = self.repo.list_expired_scheduled("ws-1", time.time())
        assert len(expired) == 1
        assert expired[0][0] == "sched1"

    def test_no_expired_before_time(self):
        """Scheduled tasks are not returned before their time."""
        import time
        future = time.time() + 3600
        self.repo.put_task("ws-1", "future", {"type": "delayed"})
        self.repo.schedule_task("ws-1", "future", {"type": "delayed"}, future)

        expired = self.repo.list_expired_scheduled("ws-1", time.time())
        assert len(expired) == 0

    def test_workspace_isolation_check(self):
        """Isolation check passes when workspaces have no overlapping IDs."""
        self.repo.put_task("ws-x", "a", {})
        self.repo.put_task("ws-y", "b", {})
        assert self.repo.assert_workspace_isolation("ws-x", "ws-y") is True

    def test_workspace_incomplete_isolation_detected(self):
        """Isolation check catches overlapping task IDs."""
        self.repo.put_task("ws-x", "shared", {})
        self.repo.put_task("ws-y", "shared", {})
        assert self.repo.assert_workspace_isolation("ws-x", "ws-y") is False

    def test_list_all_workspace_ids(self):
        """The repo tracks which workspaces have data."""
        self.repo.put_task("ws-a", "t1", {})
        self.repo.put_task("ws-b", "t2", {})
        ws_ids = self.repo.list_all_workspace_ids()
        assert "ws-a" in ws_ids
        assert "ws-b" in ws_ids


class TestTaskRepositoryEdgeCases:
    """Edge cases for the TaskRepository boundary conditions."""

    def test_empty_repo(self):
        repo = TaskRepository()
        assert repo.get_task("any", "any") is None
        assert repo.list_tasks("any") == []
        assert repo.count_by_workspace("any") == 0

    def test_large_workspace(self):
        """Many tasks in one workspace don't affect another."""
        repo = TaskRepository()
        for i in range(100):
            repo.put_task("busy", str(i), {"idx": i})
        repo.put_task("quiet", "only-one", {})

        assert repo.count_by_workspace("busy") == 100
        assert repo.count_by_workspace("quiet") == 1

    def test_workspace_id_is_added_to_task(self):
        """put_task automatically adds _workspace_id to stored tasks."""
        repo = TaskRepository()
        repo.put_task("my-ws", "t1", {"data": "hello"})
        task = repo.get_task("my-ws", "t1")
        assert task["_workspace_id"] == "my-ws"

    def test_multiple_delete_same_task(self):
        """Double-deleting a task returns False on second call."""
        repo = TaskRepository()
        repo.put_task("ws", "t", {})
        assert repo.delete_task("ws", "t") is True
        assert repo.delete_task("ws", "t") is False
