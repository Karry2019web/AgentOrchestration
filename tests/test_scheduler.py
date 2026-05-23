import pytest
from src.orchestrator.scheduler import TaskScheduler, Lease, TaskStatus


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

    def test_mark_uploading_renews_lease(self):
        self.scheduler.enqueue({"type": "test", "target_agent": "agent-1"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        lease = self.scheduler.get_lease(task_id)
        original_expiry = lease.expires_at
        assert self.scheduler.mark_uploading(task_id)
        assert lease.expires_at > original_expiry
        assert self.scheduler.is_uploading(task_id)

    def test_finish_upload_restores_lease(self):
        self.scheduler.enqueue({"type": "test", "target_agent": "agent-1"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        self.scheduler.mark_uploading(task_id)
        assert self.scheduler.is_uploading(task_id)
        self.scheduler.finish_upload(task_id)
        assert not self.scheduler.is_uploading(task_id)

    def test_lease_expiry_detection(self):
        lease = Lease("test-id", ttl=0)
        assert lease.is_expired()

    def test_lease_renewal(self):
        lease = Lease("test-id", ttl=300)
        original = lease.expires_at
        lease.renew(600)
        assert lease.expires_at > original
        assert lease.renewals == 1

    def test_lease_remaining(self):
        lease = Lease("test-id", ttl=3600)
        assert lease.remaining() > 0

    def test_recover_expired_leases(self):
        self.scheduler.enqueue({"type": "test", "target_agent": "agent-1"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        lease = self.scheduler.get_lease(task_id)
        lease.expires_at = 0
        assert lease.is_expired()
        recovered = self.scheduler.recover_expired_leases()
        assert len(recovered) > 0
        assert task_id in recovered

    def test_get_status_uploading(self):
        self.scheduler.enqueue({"type": "test", "target_agent": "agent-1"})
        import asyncio
        task = asyncio.run(self.scheduler.dequeue())
        task_id = task["id"]
        assert self.scheduler.get_status(task_id) == TaskStatus.IN_FLIGHT
        self.scheduler.mark_uploading(task_id)
        assert self.scheduler.get_status(task_id) == TaskStatus.UPLOADING
