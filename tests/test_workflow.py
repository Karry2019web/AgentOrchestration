"""Tests for workflow compensation engine."""

import pytest
from src.orchestrator.workflow import (
    WorkflowManager,
    WorkflowStep,
    CompensationEngine,
    CompensationAction,
    StepStatus,
)


class TestCompensationEngine:
    def test_compensation_not_active_by_default(self):
        engine = CompensationEngine()
        assert not engine.is_compensated
        assert not engine.downstream_blocked

    def test_block_downstream_after_trigger(self):
        engine = CompensationEngine()
        engine.trigger_compensation("step_1")
        assert engine.is_compensated
        assert engine.downstream_blocked

    def test_reset_clears_compensation_state(self):
        engine = CompensationEngine()
        engine.trigger_compensation("step_1")
        engine.reset()
        assert not engine.is_compensated
        assert not engine.downstream_blocked
        assert not engine.is_step_blocked("step_any")

    def test_compensation_executes_undo_handlers(self):
        engine = CompensationEngine()
        undo_called = []

        def undo_fn():
            undo_called.append(True)

        action = CompensationAction(
            step_id="step_1",
            step_name="Step 1",
            undo_handler=undo_fn,
        )
        engine.register_compensation(action)
        engine.trigger_compensation("step_2")
        assert len(undo_called) == 1
        assert action.executed


class TestWorkflowCompensation:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_block_downstream_after_step_failure(self):
        workflow = self.manager.create_workflow("test-block", "Test downstream blocking")
        step1 = WorkflowStep("step1", lambda: "ok")
        step2 = WorkflowStep("step2", lambda: (_ for _ in ()).throw(Exception("fail")))
        step3 = WorkflowStep("step3", lambda: "should-not-run")
        workflow.add_step(step1).add_step(step2).add_step(step3)

        result = self.manager.execute_workflow(workflow.id)
        assert not result

        step2_actual = workflow.get_step(step2.id)
        assert step2_actual.status == StepStatus.FAILED

        step3_actual = workflow.get_step(step3.id)
        assert step3_actual.status == StepStatus.BLOCKED

    def test_rolled_back_step_status_set_after_compensation(self):
        workflow = self.manager.create_workflow("test-rollback", "Test rollback status")
        step1 = WorkflowStep("step1", lambda: "ok")
        step2 = WorkflowStep("step2", lambda: (_ for _ in ()).throw(Exception("fail")))
        workflow.add_step(step1).add_step(step2)

        self.manager.execute_workflow(workflow.id)

        step1_actual = workflow.get_step(step1.id)
        assert step1_actual.status == StepStatus.ROLLED_BACK

    def test_all_steps_complete_successfully(self):
        workflow = self.manager.create_workflow("test-success", "Test all succeed")
        results = []

        def track_result(name):
            results.append(name)
            return name

        step1 = WorkflowStep("step1", lambda: track_result("step1"))
        step2 = WorkflowStep("step2", lambda: track_result("step2"))
        workflow.add_step(step1).add_step(step2)

        result = self.manager.execute_workflow(workflow.id)
        assert result
        assert workflow.status == StepStatus.COMPLETED

    def test_failure_without_downstream_does_not_error(self):
        workflow = self.manager.create_workflow("test-last-fail", "Test last step fails")
        step1 = WorkflowStep("step1", lambda: (_ for _ in ()).throw(Exception("fail")))
        workflow.add_step(step1)

        result = self.manager.execute_workflow(workflow.id)
        assert not result
        step1_actual = workflow.get_step(step1.id)
        assert step1_actual.status == StepStatus.FAILED
