"""Tests for Workflow definition parsing — conflicting timeout units."""
import pytest
from src.orchestrator.workflow import (
    Workflow,
    WorkflowManager,
    WorkflowStep,
    TimeoutUnit,
    StepStatus,
)


class TestTimeoutUnitValidation:
    """Prevent conflicting timeout units — definition parsing."""

    def test_step_accepts_timeout_unit(self):
        """A step can be created with an explicit timeout unit."""
        step = WorkflowStep("test", lambda: None, timeout=5, timeout_unit=TimeoutUnit.SECONDS)
        assert step.timeout_unit == TimeoutUnit.SECONDS
        assert step.timeout == 5

    def test_step_defaults_to_seconds(self):
        """Default timeout unit is SECONDS for backward compatibility."""
        step = WorkflowStep("test", lambda: None)
        assert step.timeout_unit == TimeoutUnit.SECONDS

    def test_consistent_units_accepted(self):
        """Adding steps with the same unit succeeds."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.MINUTES))
        wf.add_step(WorkflowStep("b", lambda: None, timeout_unit=TimeoutUnit.MINUTES))
        assert len(wf.steps) == 2

    def test_conflicting_units_second_step_raises(self):
        """Adding a step with a different unit from the first raises ValueError."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.SECONDS))
        with pytest.raises(ValueError, match="Conflicting timeout unit"):
            wf.add_step(WorkflowStep("b", lambda: None, timeout_unit=TimeoutUnit.MINUTES))

    def test_conflicting_units_seconds_vs_hours(self):
        """SECONDS vs HOURS is correctly detected as conflicting."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.HOURS))
        with pytest.raises(ValueError, match="Conflicting timeout unit"):
            wf.add_step(WorkflowStep("b", lambda: None, timeout_unit=TimeoutUnit.SECONDS))

    def test_conflicting_units_seconds_vs_milliseconds(self):
        """SECONDS vs MILLISECONDS is correctly detected as conflicting."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.MILLISECONDS))
        with pytest.raises(ValueError, match="Conflicting timeout unit"):
            wf.add_step(WorkflowStep("b", lambda: None, timeout_unit=TimeoutUnit.SECONDS))

    def test_conflicting_units_minutes_vs_hours(self):
        """MINUTES vs HOURS is correctly detected as conflicting."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.MINUTES))
        with pytest.raises(ValueError, match="Conflicting timeout unit"):
            wf.add_step(WorkflowStep("b", lambda: None, timeout_unit=TimeoutUnit.HOURS))

    def test_first_step_without_unit_is_backward_compat(self):
        """Adding a step without explicit timeout unit to an empty workflow works."""
        wf = Workflow("test")
        wf.add_step(WorkflowStep("a", lambda: None))  # defaults to SECONDS
        assert len(wf.steps) == 1
        assert wf.steps[0].timeout_unit == TimeoutUnit.SECONDS

    def test_mixed_units_across_different_workflows(self):
        """Different workflows can have different units independently."""
        wf1 = Workflow("wf1")
        wf2 = Workflow("wf2")
        wf1.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.SECONDS))
        wf2.add_step(WorkflowStep("a", lambda: None, timeout_unit=TimeoutUnit.MINUTES))
        assert wf1.steps[0].timeout_unit == TimeoutUnit.SECONDS
        assert wf2.steps[0].timeout_unit == TimeoutUnit.MINUTES

    def test_timeout_unit_to_seconds_conversion(self):
        """to_seconds converts correctly for all units."""
        assert TimeoutUnit.SECONDS.to_seconds(30) == 30
        assert TimeoutUnit.MINUTES.to_seconds(2) == 120
        assert TimeoutUnit.HOURS.to_seconds(1) == 3600
        assert TimeoutUnit.MILLISECONDS.to_seconds(5000) == 5

    def test_zero_timeout_value_accepted(self):
        """A timeout value of 0 should be valid."""
        step = WorkflowStep("zero", lambda: None, timeout=0, timeout_unit=TimeoutUnit.SECONDS)
        assert step.timeout == 0


class TestWorkflowExecution:
    def test_execute_successful_workflow(self):
        wfm = WorkflowManager()
        wf = wfm.create_workflow("test", "A test workflow")

        results = []

        def step_a():
            results.append("a")

        def step_b():
            results.append("b")

        wf.add_step(WorkflowStep("A", step_a))
        wf.add_step(WorkflowStep("B", step_b))
        assert wfm.execute_workflow(wf.id)
        assert results == ["a", "b"]

    def test_execute_workflow_step_failure(self):
        wfm = WorkflowManager()
        wf = wfm.create_workflow("fail", "Failing workflow")
        wf.add_step(WorkflowStep("fail_step", lambda: (_ for _ in ()).throw(Exception("fail"))))
        assert not wfm.execute_workflow(wf.id)
        assert wf.status == StepStatus.FAILED
