"""Tests for workflow dependency resolver — fan-in join validation."""

import pytest
from src.orchestrator.workflow import (
    WorkflowManager,
    Workflow,
    WorkflowStep,
    StepStatus,
)


class TestWorkflowDependencyResolver:
    """Regression tests for the fan-in joins trigger."""

    def setup_method(self):
        self.manager = WorkflowManager()

    def _handler_ok(self):
        return "ok"

    def _handler_fail(self):
        raise ValueError("intentional failure")

    def test_simple_sequential_dependencies(self):
        workflow = self.manager.create_workflow("test-seq")
        step_a = WorkflowStep("step_a", lambda: "a")
        step_b = WorkflowStep("step_b", lambda: "b")
        step_c = WorkflowStep("step_c", lambda: "c")
        workflow.add_step(step_a)
        workflow.add_step(step_b, depends_on=[step_a.name])
        workflow.add_step(step_c, depends_on=[step_b.name])
        result = self.manager.execute_workflow(workflow.id)
        assert result is True
        assert workflow.status == StepStatus.COMPLETED

    def test_fan_in_join_with_failed_dependency(self):
        workflow = self.manager.create_workflow("test-fan-in-fail")
        step_a = WorkflowStep("step_a", self._handler_fail)
        step_b = WorkflowStep("step_b", self._handler_ok)
        step_c = WorkflowStep("step_c", self._handler_ok, depends_on=["step_a", "step_b"])
        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step(step_c)
        result = self.manager.execute_workflow(workflow.id)
        assert result is False
        assert workflow.status == StepStatus.FAILED
        assert step_c.status == StepStatus.FAILED_DEPENDENCY
        assert "Dependency step" in step_c.error

    def test_fan_in_join_all_ok(self):
        workflow = self.manager.create_workflow("test-fan-in-ok")
        step_a = WorkflowStep("step_a", self._handler_ok)
        step_b = WorkflowStep("step_b", self._handler_ok)
        step_c = WorkflowStep("step_c", self._handler_ok, depends_on=["step_a", "step_b"])
        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step(step_c)
        result = self.manager.execute_workflow(workflow.id)
        assert result is True
        assert workflow.status == StepStatus.COMPLETED

    def test_cascading_fan_in_failure(self):
        workflow = self.manager.create_workflow("test-cascade")
        step_a = WorkflowStep("step_a", self._handler_fail)
        step_b = WorkflowStep("step_b", self._handler_ok, depends_on=["step_a"])
        step_c = WorkflowStep("step_c", self._handler_ok, depends_on=["step_b"])
        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step(step_c)
        result = self.manager.execute_workflow(workflow.id)
        assert result is False
        assert workflow.status == StepStatus.FAILED
        assert step_b.status == StepStatus.FAILED_DEPENDENCY
        assert step_c.status == StepStatus.FAILED_DEPENDENCY

    def test_no_dependencies_unchanged(self):
        workflow = self.manager.create_workflow("test-no-dep")
        step_a = WorkflowStep("step_a", self._handler_ok)
        step_b = WorkflowStep("step_b", self._handler_ok)
        workflow.add_step(step_a)
        workflow.add_step(step_b)
        result = self.manager.execute_workflow(workflow.id)
        assert result is True

    def test_cycle_detection(self):
        workflow = self.manager.create_workflow("test-cycle")
        step_a = WorkflowStep("step_a", self._handler_ok)
        step_b = WorkflowStep("step_b", self._handler_ok)
        step_c = WorkflowStep("step_c", self._handler_ok)
        workflow.add_step(step_a)
        workflow.add_step(step_b, depends_on=[step_a.name])
        workflow.add_step(step_c, depends_on=[step_b.name])
        workflow._dependencies[step_a.id] = {step_c.id}
        result = self.manager.execute_workflow(workflow.id)
        assert result is False

    def test_empty_workflow_still_works(self):
        workflow = self.manager.create_workflow("test-empty")
        result = self.manager.execute_workflow(workflow.id)
        assert result is True

    def test_missing_workflow_returns_false(self):
        result = self.manager.execute_workflow("non-existent")
        assert result is False
