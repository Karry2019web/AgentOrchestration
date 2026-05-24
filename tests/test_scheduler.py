import pytest
from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

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

    # --- Leader election tests ---

    def test_leader_acquire(self):
        s = TaskScheduler(instance_id="node-a")
        assert s._acquire_leadership() is True
        assert s._is_leader() is True

    def test_leader_only_one(self):
        s1 = TaskScheduler(instance_id="node-a")
        s2 = TaskScheduler(instance_id="node-b")
        # s1 acquires leadership
        assert s1._acquire_leadership() is True
        # s2 cannot acquire while s1 holds the lease
        assert s2._acquire_leadership() is False
        assert s2._is_leader() is False

    def test_leader_release(self):
        s = TaskScheduler(instance_id="node-a")
        s._acquire_leadership()
        assert s._is_leader() is True
        s._release_leadership()
        assert s._is_leader() is False

    def test_leader_reacquire_after_expiry(self):
        s1 = TaskScheduler(instance_id="node-a", lease_ttl=0.001)
        s2 = TaskScheduler(instance_id="node-b", lease_ttl=0.001)
        s1._acquire_leadership()
        assert s1._is_leader() is True
        # After lease expires, s2 can acquire
        import time
        time.sleep(0.005)
        assert s2._acquire_leadership() is True
        assert s1._is_leader() is False
        assert s2._is_leader() is True

    # --- Job deduplication tests ---

    def test_register_job_as_leader(self):
        s = TaskScheduler(instance_id="node-a")
        s._acquire_leadership()
        task_id = s.register_job("daily-cleanup", {"type": "cleanup"})
        assert task_id is not None
        assert "daily-cleanup" in s.list_registered_jobs()

    def test_register_job_non_leader_returns_none(self):
        s1 = TaskScheduler(instance_id="node-a")
        s2 = TaskScheduler(instance_id="node-b")
        s1._acquire_leadership()
        # s2 is not the leader
        task_id = s2.register_job("daily-cleanup", {"type": "cleanup"})
        assert task_id is None

    def test_register_duplicate_job_returns_none(self):
        s = TaskScheduler(instance_id="node-a")
        s._acquire_leadership()
        first = s.register_job("daily-cleanup", {"type": "cleanup"})
        second = s.register_job("daily-cleanup", {"type": "cleanup"})
        assert first is not None
        assert second is None  # Duplicate rejected

    def test_register_different_jobs_both_accepted(self):
        s = TaskScheduler(instance_id="node-a")
        s._acquire_leadership()
        id1 = s.register_job("daily-cleanup", {"type": "cleanup"})
        id2 = s.register_job("hourly-report", {"type": "report"})
        assert id1 is not None
        assert id2 is not None
        assert len(s.list_registered_jobs()) == 2

    def test_unregister_job(self):
        s = TaskScheduler(instance_id="node-a")
        s._acquire_leadership()
        s.register_job("daily-cleanup", {"type": "cleanup"})
        assert s.unregister_job("daily-cleanup") is True
        assert "daily-cleanup" not in s.list_registered_jobs()

    def test_unregister_job_non_owner_fails(self):
        s1 = TaskScheduler(instance_id="node-a")
        s2 = TaskScheduler(instance_id="node-b")
        s1._acquire_leadership()
        s1.register_job("daily-cleanup", {"type": "cleanup"})
        # s2 cannot unregister jobs it does not own
        assert s2.unregister_job("daily-cleanup") is False

    def test_rolling_deployment_simulation(self):
        """Simulate rolling deployment scenario from the issue."""
        old_scheduler = TaskScheduler(instance_id="old-v1")
        new_scheduler = TaskScheduler(instance_id="new-v2")

        # Old scheduler acquires leadership and registers jobs
        old_scheduler._acquire_leadership()
        old_id = old_scheduler.register_job("daily-cleanup", {"type": "cleanup"})
        assert old_id is not None

        # New scheduler comes online but cannot register the same job
        new_id = new_scheduler.register_job("daily-cleanup", {"type": "cleanup"})
        assert new_id is None  # Duplicate prevented

        # Old scheduler lease expires, new scheduler takes over
        old_scheduler._release_leadership()
        new_scheduler._acquire_leadership()
        new_id = new_scheduler.register_job("hourly-report", {"type": "report"})
        assert new_id is not None
        assert len(new_scheduler.list_registered_jobs()) == 1
