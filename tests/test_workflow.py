"""Tests for Workflow compensating actions and rollback."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from orchestrator.workflow import WorkflowManager, WorkflowStep, StepStatus


def test_compensating_action_executed_on_failure():
    wm = WorkflowManager()
    wf = wm.create_workflow("test")
    comp_called = []

    def step1():
        return "ok"

    def comp1():
        comp_called.append("comp1")

    step = WorkflowStep("step1", step1)
    step.set_compensating_action(comp1)
    wf.add_step(step)

    def step2():
        raise ValueError("fail")

    wf.add_step(WorkflowStep("step2", step2))

    result = wm.execute_workflow(wf.id)
    assert result is False
    assert len(comp_called) == 1
    assert comp_called[0] == "comp1"


def test_rollback_workflow():
    wm = WorkflowManager()
    wf = wm.create_workflow("test")
    comp_called = []

    def step1():
        return "ok"

    def comp1():
        comp_called.append("comp1")

    s1 = WorkflowStep("step1", step1)
    s1.set_compensating_action(comp1)
    wf.add_step(s1)

    def step2():
        return "ok"

    s2 = WorkflowStep("step2", step2)
    s2.set_compensating_action(lambda: comp_called.append("comp2"))
    wf.add_step(s2)

    wm.execute_workflow(wf.id)
    wm.rollback_workflow(wf.id)

    assert len(comp_called) == 2
    # Compensating actions should run in reverse order
    assert comp_called == ["comp2", "comp1"]


def test_no_compensating_action_does_not_crash():
    wm = WorkflowManager()
    wf = wm.create_workflow("test")

    def step1():
        return "ok"

    wf.add_step(WorkflowStep("step1", step1))

    def step2():
        raise ValueError("fail")

    wf.add_step(WorkflowStep("step2", step2))

    result = wm.execute_workflow(wf.id)
    assert result is False


def test_execute_unknown_workflow():
    wm = WorkflowManager()
    assert wm.execute_workflow("unknown") is False
