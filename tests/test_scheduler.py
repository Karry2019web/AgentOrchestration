import pytest
from src.orchestrator.scheduler import TaskScheduler, WorkspaceScopedStore


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}}, workspace_id="ws-1")
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, workspace_id="ws-1", priority=1)
        self.scheduler.enqueue({"type": "high"}, workspace_id="ws-1", priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert self.scheduler.complete(task["id"], workspace_id="ws-1")

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert self.scheduler.fail(task["id"], workspace_id="ws-1")

    def test_cross_workspace_isolation_enqueue(self):
        self.scheduler.enqueue({"type": "ws1-task"}, workspace_id="ws-1")
        self.scheduler.enqueue({"type": "ws2-task"}, workspace_id="ws-2")
        import asyncio
        task_ws1 = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task_ws1 is not None
        assert task_ws1["type"] == "ws1-task"
        task_ws2 = asyncio.run(self.scheduler.dequeue(workspace_id="ws-2"))
        assert task_ws2 is not None
        assert task_ws2["type"] == "ws2-task"

    def test_cross_workspace_complete_fails(self):
        self.scheduler.enqueue({"type": "test"}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task is not None
        assert not self.scheduler.complete(task["id"], workspace_id="ws-2")
        assert self.scheduler.complete(task["id"], workspace_id="ws-1")

    def test_cross_workspace_fail_fails(self):
        self.scheduler.enqueue({"type": "test"}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task is not None
        assert not self.scheduler.fail(task["id"], workspace_id="ws-2")
        assert self.scheduler.fail(task["id"], workspace_id="ws-1")

    def test_get_in_flight_scoped(self):
        self.scheduler.enqueue({"type": "test"}, workspace_id="ws-1")
        import asyncio
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task is not None
        assert self.scheduler.get_in_flight(task["id"], workspace_id="ws-1") is not None
        assert self.scheduler.get_in_flight(task["id"], workspace_id="ws-2") is None

    def test_list_in_flight_scoped(self):
        self.scheduler.enqueue({"type": "ws1"}, workspace_id="ws-1")
        self.scheduler.enqueue({"type": "ws2"}, workspace_id="ws-2")
        import asyncio
        asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        asyncio.run(self.scheduler.dequeue(workspace_id="ws-2"))
        ws1_tasks = self.scheduler.list_in_flight("ws-1")
        ws2_tasks = self.scheduler.list_in_flight("ws-2")
        assert len(ws1_tasks) == 1
        assert len(ws2_tasks) == 1
        assert all(t["workspace_id"] == "ws-1" for t in ws1_tasks)
        assert all(t["workspace_id"] == "ws-2" for t in ws2_tasks)

    def test_task_id_collision_across_workspaces(self):
        store = WorkspaceScopedStore()
        task = {"type": "collision-test"}
        task_id = store.enqueue(task, workspace_id="ws-alpha")
        assert store.get_task_workspace(task_id) == "ws-alpha"
        assert store.get_task_workspace("nonexistent") is None

    def test_missing_workspace_raises(self):
        import asyncio
        with pytest.raises(ValueError):
            self.scheduler.enqueue({"type": "test"}, workspace_id="")
        with pytest.raises(ValueError):
            asyncio.run(self.scheduler.dequeue(workspace_id=""))

    def test_schedule_with_workspace(self):
        self.scheduler.schedule({"type": "delayed"}, workspace_id="ws-1", delay=0.01)
        import asyncio
        import time
        time.sleep(0.02)
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-1"))
        assert task is not None
        assert task["type"] == "delayed"

    def test_schedule_cross_workspace_isolation(self):
        self.scheduler.schedule({"type": "delayed-ws1"}, workspace_id="ws-1", delay=0.01)
        import asyncio
        import time
        time.sleep(0.02)
        task = asyncio.run(self.scheduler.dequeue(workspace_id="ws-2"))
        assert task is None
