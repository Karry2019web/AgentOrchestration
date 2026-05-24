"""Tests for workflow compensation engine — partial rollback."""

import pytest
from src.orchestrator.workflow import (
    Workflow,
    WorkflowStep,
    WorkflowManager,
    CompensationEngine,
    CompensationResult,
    StepStatus,
)


class TestCompensationEngine:
    def test_start_rollback_accepts_first_request(self):
        engine = CompensationEngine()
        result = engine.start_rollback("wf-1", "step-2")
        assert result == CompensationResult.ACCEPTED
        assert engine.is_rollback_active

    def test_start_rollback_rejects_duplicate(self):
        engine = CompensationEngine()
        engine.start_rollback("wf-1", "step-2")
        result = engine.start_rollback("wf-1", "step-3")
        assert result == CompensationResult.REJECTED

    def test_compensate_step_executes_handler(self):
        engine = CompensationEngine()
        compensated = []

        def comp():
            compensated.append(True)

        step = WorkflowStep("test-step", lambda: None, compensation=comp)
        step.status = StepStatus.COMPLETED
        engine.start_rollback("wf-1", "step-fail")
        result = engine.compensate_step(step)
        assert result
        assert compensated == [True]
        assert step.status == StepStatus.COMPENSATED

    def test_compensate_step_skips_duplicate(self):
        engine = CompensationEngine()
        step = WorkflowStep("test-step", lambda: None)
        step.status = StepStatus.COMPLETED

        engine.start_rollback("wf-1", "step-fail")
        engine.compensate_step(step)
        result = engine.compensate_step(step)
        assert not result  # Already compensated

    def test_compensate_step_without_handler(self):
        engine = CompensationEngine()
        step = WorkflowStep("no-comp-step", lambda: None)
        step.status = StepStatus.COMPLETED

        engine.start_rollback("wf-1", "step-fail")
        result = engine.compensate_step(step)
        assert result
        assert step.status == StepStatus.COMPENSATED

    def test_finalize_rollback_clears_active(self):
        engine = CompensationEngine()
        engine.start_rollback("wf-1", "step-fail")
        engine.finalize_rollback("wf-1")
        assert not engine.is_rollback_active


class TestWorkflowCompensation:
    def test_partial_rollback_compensates_completed_steps(self):
        """After step 2 fails, step 1 should be compensated and step 3+ blocked."""
        compensated = []

        def comp1():
            compensated.append("step1")

        def handler_ok():
            return "ok"

        def handler_fail():
            raise ValueError("simulated failure")

        step1 = WorkflowStep("step-1", handler_ok, compensation=comp1)
        step2 = WorkflowStep("step-2", handler_fail)
        step3 = WorkflowStep("step-3", handler_ok)

        mgr = WorkflowManager()
        wf = mgr.create_workflow("test-rollback")
        wf.add_step(step1).add_step(step2).add_step(step3)

        result = mgr.execute_workflow(wf.id)
        assert not result  # Workflow should fail
        assert wf.status == StepStatus.FAILED

        # Step 1 should be compensated
        assert step1.status == StepStatus.COMPENSATED
        assert compensated == ["step1"]

        # Step 2 should be failed
        assert step2.status == StepStatus.FAILED

        # Step 3 should be blocked (skipped)
        assert step3.status == StepStatus.SKIPPED

    def test_no_compensation_for_single_step_workflow(self):
        """A single-step workflow that fails has no completed steps to compensate."""
        def handler_fail():
            raise ValueError("boom")

        step = WorkflowStep("only-step", handler_fail)
        mgr = WorkflowManager()
        wf = mgr.create_workflow("single-fail")
        wf.add_step(step)

        result = mgr.execute_workflow(wf.id)
        assert not result
        assert step.status == StepStatus.FAILED

    def test_rollback_not_started_if_all_succeed(self):
        """A successful workflow should not trigger any compensation."""
        results = []

        def track():
            results.append("done")

        step1 = WorkflowStep("step-1", track)
        step2 = WorkflowStep("step-2", track)
        mgr = WorkflowManager()
        wf = mgr.create_workflow("happy-path")
        wf.add_step(step1).add_step(step2)

        result = mgr.execute_workflow(wf.id)
        assert result
        assert wf.status == StepStatus.COMPLETED
        assert not wf.compensation_engine.is_rollback_active
        assert results == ["done", "done"]

    def test_upstream_compensation_order(self):
        """Completed steps should be compensated in reverse order."""
        order = []

        def comp_a():
            order.append("A")

        def comp_b():
            order.append("B")

        step_a = WorkflowStep("step-a", lambda: "ok", compensation=comp_a)
        step_b = WorkflowStep("step-b", lambda: "ok", compensation=comp_b)
        step_c = WorkflowStep("step-c", lambda: (_ for _ in ()).throw(ValueError("fail")))

        mgr = WorkflowManager()
        wf = mgr.create_workflow("reverse-order")
        wf.add_step(step_a).add_step(step_b).add_step(step_c)

        result = mgr.execute_workflow(wf.id)
        assert not result
        # Compensation should run B first, then A (reverse order)
        assert order == ["B", "A"]


class TestWorkflowManager:
    def test_execute_nonexistent_workflow(self):
        mgr = WorkflowManager()
        assert not mgr.execute_workflow("nonexistent-id")

    def test_create_and_list(self):
        mgr = WorkflowManager()
        wf1 = mgr.create_workflow("wf-1")
        wf2 = mgr.create_workflow("wf-2")
        assert len(mgr.list_workflows()) == 2

    def test_delete_workflow(self):
        mgr = WorkflowManager()
        wf = mgr.create_workflow("to-delete")
        assert mgr.delete_workflow(wf.id)
        assert mgr.get_workflow(wf.id) is None

    def test_get_step_by_id(self):
        step = WorkflowStep("named-step", lambda: None)
        wf = Workflow("test")
        wf.add_step(step)
        assert wf.get_step(step.id) is step
        assert wf.get_step("nonexistent") is None
