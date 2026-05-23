import pytest
from src.orchestrator.scheduler import TaskScheduler, VisibilityTimeoutManager, VisibilityTimeoutError


class TestVisibilityTimeoutManager:
    def setup_method(self):
        self.vm = VisibilityTimeoutManager(default_timeout=60.0, max_extensions=3)

    def test_claim_and_check(self):
        deadline = self.vm.claim("task-1", "worker-1", timeout=60.0)
        assert deadline > 0
        assert not self.vm.is_expired("task-1")
        assert self.vm.get_worker("task-1") == "worker-1"

    def test_extend_visibility(self):
        self.vm.claim("task-1", "worker-1", timeout=30.0)
        import time
        original_deadline = self.vm.get_deadline("task-1")
        time.sleep(0.001)
        new_deadline = self.vm.extend("task-1", "worker-1", extension=60.0)
        assert new_deadline > original_deadline

    def test_extend_wrong_worker_raises(self):
        self.vm.claim("task-1", "worker-1", timeout=60.0)
        with pytest.raises(VisibilityTimeoutError):
            self.vm.extend("task-1", "worker-2")

    def test_release(self):
        self.vm.claim("task-1", "worker-1")
        self.vm.release("task-1", "worker-1")
        assert self.vm.get_worker("task-1") is None
        assert self.vm.is_expired("task-1") is True

    def test_release_wrong_worker_raises(self):
        self.vm.claim("task-1", "worker-1")
        with pytest.raises(VisibilityTimeoutError):
            self.vm.release("task-1", "worker-2")

    def test_sweep_expired(self):
        vm = VisibilityTimeoutManager(default_timeout=0.0)
        vm.claim("task-1", "worker-1", timeout=0.0)
        import time
        time.sleep(0.01)
        expired = vm.sweep_expired()
        assert "task-1" in expired
        assert vm.is_expired("task-1") is True

    def test_max_extensions_warning(self):
        vm = VisibilityTimeoutManager(default_timeout=60.0, max_extensions=2)
        vm.claim("task-1", "worker-1")
        vm.extend("task-1", "worker-1")
        vm.extend("task-1", "worker-1")
        vm.extend("task-1", "worker-1")
        assert vm._extensions["task-1"] == 3


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler(default_visibility_timeout=60.0)

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_extend_visibility_timeout(self):
        self.scheduler.enqueue({"type": "long_running"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        new_deadline = self.scheduler.extend_visibility(task["id"], extension=120.0)
        assert new_deadline > 0
        assert not self.scheduler.get_visibility().is_expired(task["id"])

    def test_dequeue_sets_visibility(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        vm = self.scheduler.get_visibility()
        assert not vm.is_expired(task["id"])
        assert vm.get_worker(task["id"]) is not None

    def test_complete_releases_visibility(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.complete(task["id"])
        assert self.scheduler.get_visibility().is_expired(task["id"])

    def test_fail_releases_visibility(self):
        self.scheduler.enqueue({"type": "test"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        self.scheduler.fail(task["id"])
        assert self.scheduler.get_visibility().is_expired(task["id"])
