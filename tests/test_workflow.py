"""Tests for workflow condition evaluation (sandbox expression side effects)."""

import importlib.util
from pathlib import Path

WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / "src/orchestrator/workflow.py"
)
SPEC = importlib.util.spec_from_file_location("workflow_module", WORKFLOW_PATH)
workflow_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow_module)

StepStatus = workflow_module.StepStatus
WorkflowManager = workflow_module.WorkflowManager
WorkflowStep = workflow_module.WorkflowStep


class TestWorkflowConditionEvaluation:
    def setup_method(self):
        self.manager = WorkflowManager()
        self.workflow = self.manager.create_workflow("guarded")

    def test_step_runs_when_condition_is_none(self):
        """Steps without a condition execute normally."""
        called = []
        step = WorkflowStep("safe", lambda: called.append("done"))
        self.workflow.add_step(step)
        assert self.manager.execute_workflow(self.workflow.id)
        assert called == ["done"]
        assert step.status is StepStatus.COMPLETED

    def test_step_runs_when_condition_returns_true(self):
        """Steps with condition=True execute their handler."""
        called = []
        step = WorkflowStep("conditioned", lambda: called.append("done"),
                            condition=lambda: True)
        self.workflow.add_step(step)
        assert self.manager.execute_workflow(self.workflow.id)
        assert called == ["done"]
        assert step.status is StepStatus.COMPLETED

    def test_step_is_skipped_when_condition_returns_false(self):
        """Steps with condition=False are skipped without running handler."""
        called = []
        step = WorkflowStep("skip", lambda: called.append(True),
                            condition=lambda: False)
        self.workflow.add_step(step)
        assert self.manager.execute_workflow(self.workflow.id)
        assert called == []
        assert step.status is StepStatus.SKIPPED

    def test_skipped_step_does_not_block_subsequent_steps(self):
        """Skipped steps allow the rest of the workflow to continue."""
        results = []
        step_a = WorkflowStep("skip-a", lambda: results.append("a"),
                              condition=lambda: False)
        step_b = WorkflowStep("run-b", lambda: results.append("b"))
        self.workflow.add_step(step_a).add_step(step_b)
        assert self.manager.execute_workflow(self.workflow.id)
        assert results == ["b"]
        assert step_a.status is StepStatus.SKIPPED
        assert step_b.status is StepStatus.COMPLETED
        assert self.workflow.status is StepStatus.COMPLETED

    def test_condition_exception_fails_workflow(self):
        """An exception in the condition callable fails the workflow."""
        def bad_condition():
            raise RuntimeError("condition exploded")

        step = WorkflowStep("bomb", lambda: "nope", condition=bad_condition)
        self.workflow.add_step(step)
        assert not self.manager.execute_workflow(self.workflow.id)
        assert step.status is StepStatus.FAILED
        assert "condition raised" in step.error
        assert self.workflow.status is StepStatus.FAILED

    def test_condition_side_effects_on_step_status_rejected(self):
        """Condition mutating step status is detected and rejected."""
        def mutating_condition():
            step.status = StepStatus.COMPLETED
            return True

        step = WorkflowStep("mutator", lambda: "ok", condition=mutating_condition)
        self.workflow.add_step(step)
        assert not self.manager.execute_workflow(self.workflow.id)
        assert step.status is StepStatus.FAILED
        assert "side effects" in step.error
        assert self.workflow.status is StepStatus.FAILED

    def test_condition_side_effects_on_workflow_status_rejected(self):
        """Condition mutating workflow status is detected and restored."""
        def status_mutator():
            self.workflow.status = StepStatus.COMPLETED
            return True

        step = WorkflowStep("wf-mutator", lambda: "ok", condition=status_mutator)
        self.workflow.add_step(step)
        assert not self.manager.execute_workflow(self.workflow.id)
        assert step.status is StepStatus.FAILED
        assert self.workflow.status is StepStatus.FAILED

    def test_condition_side_effects_on_sibling_step_rejected(self):
        """Condition mutating another step's result is detected."""
        innocent = WorkflowStep("innocent", lambda: "ok")

        def sibling_mutator():
            innocent.result = "tampered"
            return True

        step = WorkflowStep("sibling-attack", lambda: "ok",
                            condition=sibling_mutator)
        self.workflow.add_step(step).add_step(innocent)
        assert not self.manager.execute_workflow(self.workflow.id)
        assert step.status is StepStatus.FAILED
        assert innocent.result is None

    def test_non_boolean_condition_is_rejected(self):
        """Condition returning non-boolean value is rejected."""
        step = WorkflowStep("bad-return", lambda: "should-not-run",
                            condition=lambda: "yes")
        self.workflow.add_step(step)
        assert not self.manager.execute_workflow(self.workflow.id)
        assert step.status is StepStatus.FAILED
        assert "must return bool" in step.error

    def test_audit_log_records_skip_decision(self):
        """Audit log captures the skip decision with reason."""
        step = WorkflowStep("data-dependent", lambda: "ok",
                            condition=lambda: False)
        self.workflow.add_step(step)
        self.manager.execute_workflow(self.workflow.id)
        assert len(self.workflow.audit_log) >= 1
        entry = self.workflow.audit_log[-1]
        assert entry["decision"] == "skipped"
        assert entry["step_id"] == step.id
        assert entry["step_name"] == "data-dependent"

    def test_audit_log_records_accept_decision(self):
        """Audit log captures the accept decision with reason."""
        step = WorkflowStep("data-pass", lambda: "ok",
                            condition=lambda: True)
        self.workflow.add_step(step)
        self.manager.execute_workflow(self.workflow.id)
        assert len(self.workflow.audit_log) >= 1
        entry = self.workflow.audit_log[-1]
        assert entry["decision"] == "accepted"
        assert entry["step_name"] == "data-pass"

    def test_audit_log_records_reject_decision(self):
        """Audit log captures rejection for side-effecting conditions."""
        def bad_cond():
            step.status = StepStatus.COMPLETED
            return True

        step = WorkflowStep("attacker", lambda: "ok", condition=bad_cond)
        self.workflow.add_step(step)
        self.manager.execute_workflow(self.workflow.id)
        assert len(self.workflow.audit_log) >= 1
        entry = self.workflow.audit_log[-1]
        assert entry["decision"] == "rejected"
        assert step.status is StepStatus.FAILED

    def test_workflow_completes_with_multiple_conditioned_steps(self):
        """Workflow with multiple steps, some conditioned, all pass."""
        results = []
        s1 = WorkflowStep("a", lambda: results.append("a"), condition=lambda: True)
        s2 = WorkflowStep("b", lambda: results.append("b"))
        s3 = WorkflowStep("c", lambda: results.append("c"), condition=lambda: False)
        s4 = WorkflowStep("d", lambda: results.append("d"), condition=lambda: True)
        self.workflow.add_step(s1).add_step(s2).add_step(s3).add_step(s4)
        assert self.manager.execute_workflow(self.workflow.id)
        assert results == ["a", "b", "d"]
        assert s1.status is StepStatus.COMPLETED
        assert s2.status is StepStatus.COMPLETED
        assert s3.status is StepStatus.SKIPPED
        assert s4.status is StepStatus.COMPLETED
        assert self.workflow.status is StepStatus.COMPLETED
