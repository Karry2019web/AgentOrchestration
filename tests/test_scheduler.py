import asyncio

from src.orchestrator.scheduler import TaskScheduler


class TestTaskScheduler:
    def setup_method(self):
        self.scheduler = TaskScheduler()

    def test_enqueue_task(self):
        task_id = self.scheduler.enqueue({"type": "test", "payload": {}})
        assert task_id is not None

    def test_dequeue_task(self):
        self.scheduler.enqueue({"type": "test", "payload": {"data": 1}})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "test"

    def test_enqueue_multiple_priorities(self):
        self.scheduler.enqueue({"type": "low"}, priority=1)
        self.scheduler.enqueue({"type": "high"}, priority=10)
        task = asyncio.run(self.scheduler.dequeue())
        assert task["type"] == "high"

    def test_complete_task(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.complete(task["id"])

    def test_fail_task_with_retry(self):
        self.scheduler.enqueue({"type": "test"})
        task = asyncio.run(self.scheduler.dequeue())
        assert self.scheduler.fail(task["id"])

    def test_pause_tenant_defers_tasks(self):
        self.scheduler.pause_tenant("tenant-a", reason="deploy")
        self.scheduler.enqueue({"type": "job", "tenant_id": "tenant-a"})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is None, "Paused tenant tasks should be deferred"

    def test_paused_tenant_does_not_block_other_tenants(self):
        self.scheduler.pause_tenant("tenant-a", reason="deploy")
        self.scheduler.enqueue({"type": "job-a", "tenant_id": "tenant-a"}, priority=10)
        self.scheduler.enqueue({"type": "job-b", "tenant_id": "tenant-b"}, priority=1)
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["tenant_id"] == "tenant-b"
        assert task["type"] == "job-b"

    def test_resume_tenant_releases_bounded_backlog(self):
        scheduler = TaskScheduler(resume_batch_size=2)
        scheduler.pause_tenant("tenant-a", reason="deploy-old")
        for i in range(3):
            scheduler.enqueue({"type": f"backlog-{i}", "tenant_id": "tenant-a"}, priority=10 - i)

        assert scheduler.resume_tenant("tenant-a")

        first = asyncio.run(scheduler.dequeue_with_tenant_gate())
        second = asyncio.run(scheduler.dequeue_with_tenant_gate())
        third = asyncio.run(scheduler.dequeue_with_tenant_gate())

        assert first is not None
        assert first["type"] == "backlog-0"
        assert second is not None
        assert second["type"] == "backlog-1"
        assert third is None, "Third task should be deferred (batch exhausted)"

        assert any(
            e["action"] == "defer_resume_burst"
            for e in scheduler.audit_events
        )

    def test_advance_resume_window(self):
        scheduler = TaskScheduler(resume_batch_size=2)
        scheduler.pause_tenant("tenant-a")
        for i in range(4):
            scheduler.enqueue({"type": f"job-{i}", "tenant_id": "tenant-a"})
        scheduler.resume_tenant("tenant-a")

        first = asyncio.run(scheduler.dequeue_with_tenant_gate())
        second = asyncio.run(scheduler.dequeue_with_tenant_gate())
        assert first is not None and second is not None
        third = asyncio.run(scheduler.dequeue_with_tenant_gate())
        assert third is None

        assert scheduler.advance_resume_window("tenant-a", batch_size=2)
        third = asyncio.run(scheduler.dequeue_with_tenant_gate())
        fourth = asyncio.run(scheduler.dequeue_with_tenant_gate())
        assert third is not None and fourth is not None
        fifth = asyncio.run(scheduler.dequeue_with_tenant_gate())
        assert fifth is None

    def test_resume_nonexistent_tenant(self):
        assert not self.scheduler.resume_tenant("nonexistent")

    def test_pause_without_tenant_id(self):
        try:
            self.scheduler.pause_tenant("")
            assert False, "Should have raised ValueError"
        except ValueError:
            pass

    def test_audit_events_recorded(self):
        self.scheduler.pause_tenant("tenant-x", reason="maintenance")
        self.scheduler.resume_tenant("tenant-x")
        events = self.scheduler.audit_events
        assert len(events) == 2
        assert events[0]["action"] == "pause"
        assert events[0]["tenant_id"] == "tenant-x"
        assert events[1]["action"] == "resume"

    def test_audit_events_not_leaking_runtime_data(self):
        self.scheduler.pause_tenant("tenant-y")
        for event in self.scheduler.audit_events:
            assert "token" not in event
            assert "secret" not in event
            assert "password" not in event

    def test_dequeue_non_tenant_task_unaffected_by_pause(self):
        self.scheduler.pause_tenant("tenant-a")
        self.scheduler.enqueue({"type": "system-task"})
        task = asyncio.run(self.scheduler.dequeue())
        assert task is not None
        assert task["type"] == "system-task"

    def test_is_tenant_paused(self):
        assert not self.scheduler.is_tenant_paused("tenant-a")
        self.scheduler.pause_tenant("tenant-a")
        assert self.scheduler.is_tenant_paused("tenant-a")
        self.scheduler.resume_tenant("tenant-a")
        assert not self.scheduler.is_tenant_paused("tenant-a")

    def test_is_tenant_resuming(self):
        assert not self.scheduler.is_tenant_resuming("tenant-a")
        self.scheduler.pause_tenant("tenant-a")
        assert not self.scheduler.is_tenant_resuming("tenant-a")
        self.scheduler.resume_tenant("tenant-a")
        assert self.scheduler.is_tenant_resuming("tenant-a")
