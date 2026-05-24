"""Tests for TaskScheduler workflow deletion guard."""

import asyncio
import time
import pytest
from src.orchestrator.scheduler import TaskScheduler, WorkflowDeletedError
from src.orchestrator.workflow import WorkflowManager


class TestWorkflowDeletionGuard:
    def setup_method(self):
        self.scheduler = TaskScheduler()
        self.wfm = WorkflowManager()
        self.wfm.register_scheduler(self.scheduler)

    def test_enqueue_rejects_deleted_workflow(self):
        """enqueue() raises WorkflowDeletedError when workflow is deleted."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)

        with pytest.raises(WorkflowDeletedError, match=f"Cannot enqueue task for deleted workflow {wid}"):
            self.scheduler.enqueue({"type": "test", "workflow_id": wid})

    def test_schedule_rejects_deleted_workflow(self):
        """schedule() raises WorkflowDeletedError when workflow is deleted."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)

        with pytest.raises(WorkflowDeletedError, match=f"Cannot schedule task for deleted workflow {wid}"):
            self.scheduler.schedule({"type": "test", "workflow_id": wid}, delay=10)

    def test_enqueue_allows_non_deleted_workflow(self):
        """enqueue() succeeds for non-deleted workflow."""
        workflow = self.wfm.create_workflow("test")
        task_id = self.scheduler.enqueue({"type": "test", "workflow_id": workflow.id})
        assert task_id is not None

    def test_schedule_allows_non_deleted_workflow(self):
        """schedule() succeeds for non-deleted workflow."""
        workflow = self.wfm.create_workflow("test")
        task_id = self.scheduler.schedule({"type": "test", "workflow_id": workflow.id}, delay=10)
        assert task_id is not None

    def test_enqueue_allows_task_without_workflow_id(self):
        """enqueue() succeeds for tasks without a workflow_id (no guard applies)."""
        self.wfm.create_workflow("other")
        task_id = self.scheduler.enqueue({"type": "no_workflow"})
        assert task_id is not None

    def test_mark_workflow_deleted_tracks_state(self):
        """mark_workflow_deleted() correctly tracks deleted workflows."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        assert not self.scheduler.is_workflow_deleted(wid)
        self.wfm.delete_workflow(wid)
        assert self.scheduler.is_workflow_deleted(wid)

    def test_get_deleted_workflows_lists_deleted_ids(self):
        """get_deleted_workflows() returns all deleted workflow IDs."""
        w1 = self.wfm.create_workflow("a").id
        w2 = self.wfm.create_workflow("b").id
        self.wfm.delete_workflow(w1)
        self.wfm.delete_workflow(w2)
        deleted = self.scheduler.get_deleted_workflows()
        assert w1 in deleted
        assert w2 in deleted

    def test_deletion_audit_records_timestamp(self):
        """get_deletion_audit() records deletion timestamps."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)
        audit = self.scheduler.get_deletion_audit()
        assert wid in audit
        assert isinstance(audit[wid], float)

    def test_remove_deletion_marker_allows_enqueue_again(self):
        """After removing a deletion marker, enqueue succeeds again."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)
        assert self.scheduler.is_workflow_deleted(wid)

        self.scheduler.remove_workflow_deletion_marker(wid)
        assert not self.scheduler.is_workflow_deleted(wid)
        task_id = self.scheduler.enqueue({"type": "test", "workflow_id": wid})
        assert task_id is not None

    def test_deleted_workflow_audit_cleared_on_remove(self):
        """get_deletion_audit() removes entry after deletion marker is cleared."""
        workflow = self.wfm.create_workflow("test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)
        assert wid in self.scheduler.get_deletion_audit()
        self.scheduler.remove_workflow_deletion_marker(wid)
        assert wid not in self.scheduler.get_deletion_audit()

    def test_multi_scheduler_notification(self):
        """Multiple schedulers are notified on workflow deletion."""
        scheduler2 = TaskScheduler()
        self.wfm.register_scheduler(scheduler2)
        workflow = self.wfm.create_workflow("multi")
        wid = workflow.id
        self.wfm.delete_workflow(wid)
        assert self.scheduler.is_workflow_deleted(wid)
        assert scheduler2.is_workflow_deleted(wid)

    def test_delete_non_existent_workflow_no_side_effects(self):
        """Deleting a non-existent workflow returns False and doesn't notify schedulers."""
        result = self.wfm.delete_workflow("non-existent-id")
        assert result is False
        assert len(self.scheduler.get_deleted_workflows()) == 0

    def test_enqueue_uses_thread_lock(self):
        """Verify lock is acquired during enqueue for thread safety."""
        workflow = self.wfm.create_workflow("lock_test")
        wid = workflow.id
        self.wfm.delete_workflow(wid)
        with pytest.raises(WorkflowDeletedError):
            self.scheduler.enqueue({"type": "test", "workflow_id": wid})
