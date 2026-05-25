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

    # ---- Deletion-gating tests ----

    def test_gate_rejects_enqueue_after_deletion(self):
        """Run creation via enqueue must be rejected after workflow deletion."""
        self.scheduler.mark_workflow_deleted("wf-1")
        task_id = self.scheduler.enqueue(
            {"type": "run", "workflow_id": "wf-1"},
        )
        assert task_id is None, "Expected None — enqueue must be gated"

    def test_gate_rejects_schedule_after_deletion(self):
        """Run creation via schedule must be rejected after workflow deletion."""
        self.scheduler.mark_workflow_deleted("wf-2")
        task_id = self.scheduler.schedule(
            {"type": "run", "workflow_id": "wf-2"}, delay=10,
        )
        assert task_id is None, "Expected None — schedule must be gated"

    def test_enqueue_allowed_before_deletion(self):
        """Run creation must succeed before workflow deletion."""
        task_id = self.scheduler.enqueue(
            {"type": "run", "workflow_id": "wf-3"},
        )
        assert task_id is not None
        self.scheduler.mark_workflow_deleted("wf-3")

    def test_gate_only_blocks_specific_workflow(self):
        """Deletion of one workflow must not block others."""
        self.scheduler.mark_workflow_deleted("wf-a")
        task_id = self.scheduler.enqueue(
            {"type": "run", "workflow_id": "wf-b"},
        )
        assert task_id is not None, "Unrelated workflow must still be schedulable"

    def test_gate_no_workflow_id(self):
        """Tasks without a workflow_id must pass through unchanged."""
        task_id = self.scheduler.enqueue({"type": "noop"})
        assert task_id is not None
        self.scheduler.mark_workflow_deleted("some-wf")

    def test_audit_log_records_rejection(self):
        """Rejected runs must be recorded in the audit log."""
        self.scheduler.mark_workflow_deleted("wf-audit")
        self.scheduler.enqueue({"type": "run", "workflow_id": "wf-audit"})
        log = self.scheduler.get_audit_log()
        events = [e["event"] for e in log]
        assert "run_creation_rejected" in events

    def test_clear_gates_resets_state(self):
        """clear_gates must reset deletion gates for test isolation."""
        self.scheduler.mark_workflow_deleted("wf-clear")
        self.scheduler.clear_gates()
        task_id = self.scheduler.enqueue(
            {"type": "run", "workflow_id": "wf-clear"},
        )
        assert task_id is not None
