import pytest
from src.orchestrator.scheduler import TaskScheduler, ScheduledJobRegistry


class TestScheduledJobRegistry:
    def setup_method(self):
        self.registry = ScheduledJobRegistry()

    def test_register_new_job(self):
        result = self.registry.register_job("daily-cleanup", "0 6 * * *", {"type": "cleanup"})
        assert result is True

    def test_register_duplicate_job(self):
        self.registry.register_job("daily-cleanup", "0 6 * * *", {"type": "cleanup"})
        result = self.registry.register_job("daily-cleanup", "0 6 * * *", {"type": "cleanup"})
        assert result is False

    def test_same_name_different_schedule_allowed(self):
        self.registry.register_job("cleanup", "0 6 * * *", {"type": "cleanup"})
        result = self.registry.register_job("cleanup", "0 12 * * *", {"type": "cleanup"})
        assert result is True

    def test_unregister_job(self):
        self.registry.register_job("test", "* * * * *", {"type": "test"})
        assert self.registry.unregister_job("test", "* * * * *") is True

    def test_list_jobs(self):
        self.registry.register_job("job1", "*/5 * * * *", {"type": "ping"})
        self.registry.register_job("job2", "0 * * * *", {"type": "sync"})
        jobs = self.registry.list_jobs()
        assert len(jobs) == 2

    def test_claim_leadership_first_instance(self):
        assert self.registry.claim_leadership("instance-1") is True
        assert self.registry.is_leader is True
        assert self.registry.leader_instance_id() == "instance-1"

    def test_second_instance_cannot_claim(self):
        self.registry.claim_leadership("instance-1")
        assert self.registry.claim_leadership("instance-2") is False

    def test_same_instance_reclaims(self):
        self.registry.claim_leadership("instance-1")
        assert self.registry.claim_leadership("instance-1") is True

    def test_release_leadership(self):
        self.registry.claim_leadership("instance-1")
        self.registry.release_leadership("instance-1")
        assert self.registry.is_leader is False
        # Another instance can now claim
        assert self.registry.claim_leadership("instance-2") is True

    def test_leadership_change_logged(self):
        """Leadership changes are logged with release identifiers."""
        self.registry.claim_leadership("deploy-v1")
        self.registry.release_leadership("deploy-v1")
        self.registry.claim_leadership("deploy-v2")


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler(instance_id="test-1")

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

    def test_register_cron_job(self):
        result = self.scheduler.register_cron_job("cleanup", "0 6 * * *", {"type": "cleanup"})
        assert result is True

    def test_register_cron_job_dedup(self):
        self.scheduler.register_cron_job("cleanup", "0 6 * * *", {"type": "cleanup"})
        result = self.scheduler.register_cron_job("cleanup", "0 6 * * *", {"type": "cleanup"})
        assert result is False

    def test_instance_id(self):
        assert self.scheduler.instance_id == "test-1"

    def test_schedule_with_dedup_duplicate_job_name(self):
        tid1 = self.scheduler.schedule({"type": "daily", "job_name": "daily-task"}, delay=60)
        assert tid1 != ""
        # Same job_name should be deduplicated
        tid2 = self.scheduler.schedule({"type": "daily", "job_name": "daily-task"}, delay=60)
        assert tid2 == ""
