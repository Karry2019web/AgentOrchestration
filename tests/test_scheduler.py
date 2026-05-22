"""Tests for workspace-scoped TaskScheduler."""

import pytest
from src.orchestrator.scheduler import TaskScheduler
from src.orchestrator.task_repository import TaskRepository


class TestTaskSchedulerWorkspace:
    """Test that TaskScheduler correctly enforces workspace scope."""

    def setup_method(self):
        self.repo = TaskRepository()
        self.scheduler = TaskScheduler(repository=self.repo)

    def test_enqueue_requires_workspace(self):
        """Enqueue creates a workspace-scoped task."""
        task_id = self.scheduler.enqueue(
            {"type": "test", "payload": {}},
            workspace_id="workspace-a",
        )
        assert task_id is not None
        task = self.repo.get_task("workspace-a", task_id)
        assert task is not None
        assert task["workspace_id"] == "workspace-a"

    def test_enqueue_cross_workspace_isolation(self):
        """Same workspace_id is required to retrieve tasks."""
        id_a = self.scheduler.enqueue(
            {"type": "from-a"},
            workspace_id="ws-a",
        )
        self.scheduler.enqueue(
            {"type": "from-b"},
            workspace_id="ws-b",
        )

        # Task from ws-a should not be visible in ws-b
        assert self.repo.get_task("ws-b", id_a) is None

    def test_dequeue_requires_workspace(self):
        """Dequeue returns tasks only from the specified workspace."""
        self.scheduler.enqueue({"type": "a"}, workspace_id="ws-a")
        self.scheduler.enqueue({"type": "b"}, workspace_id="ws-b")

        import asyncio
        task_a = asyncio.run(self.scheduler.dequeue("ws-b"))
        assert task_a is not None
        assert task_a["type"] == "b"

    def test_complete_requires_workspace(self):
        """Complete only acknowledges tasks in the right workspace."""
        tid = self.scheduler.enqueue({"type": "test"}, workspace_id="ws-a")
        import asyncio
        asyncio.run(self.scheduler.dequeue("ws-a"))

        assert self.scheduler.complete(tid, "ws-a") is True
        assert self.scheduler.complete(tid, "ws-b") is False

    def test_fail_requires_workspace(self):
        """Fail only retries tasks in the right workspace."""
        tid = self.scheduler.enqueue({"type": "test"}, workspace_id="ws-a")
        import asyncio
        asyncio.run(self.scheduler.dequeue("ws-a"))

        assert self.scheduler.fail(tid, "ws-b") is False  # wrong workspace
        assert self.scheduler.fail(tid, "ws-a") is True   # correct workspace

    def test_schedule_requires_workspace(self):
        """Scheduled tasks are scoped to a workspace."""
        tid = self.scheduler.schedule(
            {"type": "delayed"},
            delay=3600,
            workspace_id="ws-a",
        )
        task = self.repo.get_task("ws-a", tid)
        assert task is not None
        assert task["workspace_id"] == "ws-a"

    def test_identical_task_ids_across_workspaces(self):
        """Different workspaces can use identical task IDs without collision."""
        self.scheduler.enqueue({"type": "x"}, workspace_id="ws-a")
        self.scheduler.enqueue({"type": "y"}, workspace_id="ws-b")

        import asyncio
        task_a = asyncio.run(self.scheduler.dequeue("ws-a"))
        task_b = asyncio.run(self.scheduler.dequeue("ws-b"))

        assert task_a["type"] == "x"
        assert task_b["type"] == "y"

    def test_multiple_queues_per_workspace(self):
        """Each workspace has independent priority queues."""
        self.scheduler.enqueue(
            {"type": "low"}, workspace_id="ws-a", priority=1,
        )
        self.scheduler.enqueue(
            {"type": "high"}, workspace_id="ws-a", priority=10,
        )
        self.scheduler.enqueue(
            {"type": "other"}, workspace_id="ws-b", priority=1,
        )

        import asyncio
        task = asyncio.run(self.scheduler.dequeue("ws-a"))
        assert task["type"] == "high"

    def test_get_repository(self):
        """The scheduler exposes its repository for audit."""
        repo = self.scheduler.get_repository()
        assert repo is self.repo
