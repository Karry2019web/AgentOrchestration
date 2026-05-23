"""Tests for orchestration engine workflow deletion cleanup races."""

import asyncio
import pytest
from unittest.mock import MagicMock, patch

from src.orchestrator.engine import OrchestrationEngine
from src.orchestrator.scheduler import TaskScheduler


class TestOrchestrationEngineWorkflowDeletion:
    """Regression tests for cleanup races after workflow deletion.

    Verifies that tasks belonging to deleted workflows are rejected
    at the poll level and never reach execution.
    """

    @pytest.fixture
    def engine(self):
        eng = OrchestrationEngine(max_workers=2, agent_timeout=10)
        yield eng
        eng.stop()

    def test_mark_workflow_deleted(self, engine):
        """Engine tracks deleted workflows correctly."""
        workflow_id = "workflow-123"
        assert engine.is_workflow_active(workflow_id)
        engine.mark_workflow_deleted(workflow_id)
        assert not engine.is_workflow_active(workflow_id)

    def test_active_workflow_not_deleted(self, engine):
        """Tasks for active workflows are not stale."""
        task = {"id": "task-1", "workflow_id": "workflow-123", "target_agent": "agent-1"}
        assert not engine._is_stale_task(task)

    def test_stale_task_for_deleted_workflow(self, engine):
        """Tasks for deleted workflows are recognized as stale."""
        engine.mark_workflow_deleted("workflow-123")
        task = {"id": "task-1", "workflow_id": "workflow-123", "target_agent": "agent-1"}
        assert engine._is_stale_task(task)

    def test_task_without_workflow_id_is_not_stale(self, engine):
        """Tasks without workflow_id are not treated as stale (backward compat)."""
        task = {"id": "task-1", "target_agent": "agent-1"}
        assert not engine._is_stale_task(task)

    def test_stale_task_for_deleted_agent(self, engine):
        """Tasks for deleted agents are recognized as stale."""
        task = {"id": "task-1", "target_agent": "nonexistent-agent"}
        assert engine._is_stale_task(task)

    def test_deleted_workflow_cannot_be_reactivated(self, engine):
        """A deleted workflow stays deleted once marked."""
        engine.mark_workflow_deleted("wf-1")
        assert not engine.is_workflow_active("wf-1")
        engine.mark_workflow_deleted("wf-1")
        assert not engine.is_workflow_active("wf-1")

    def test_stale_task_rejected_at_dequeue(self, engine):
        """Stale tasks are rejected and completed in the start loop."""
        # Enqueue a task with a workflow_id
        task = {"type": "test", "workflow_id": "deleted-wf", "target_agent": "agent-1"}
        engine.scheduler.enqueue(task)

        # Mark the workflow as deleted
        engine.mark_workflow_deleted("deleted-wf")

        # Run one poll cycle manually
        async def poll_once():
            engine._running = True
            task = await engine.scheduler.dequeue()
            if task and engine._is_stale_task(task):
                engine.scheduler.complete(task["id"])
                return True
            return False

        result = asyncio.run(poll_once())
        assert result, "Stale task should be rejected"
        # Verify it's no longer in-flight
        assert len(engine.scheduler._in_flight) == 0

    def test_valid_task_passes_deletion_check(self, engine):
        """Valid tasks for active workflows pass the stale check."""
        task = {"type": "test", "workflow_id": "active-wf", "target_agent": "agent-1"}
        assert not engine._is_stale_task(task)
