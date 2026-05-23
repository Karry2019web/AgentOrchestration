"""Tests for Workflow fan-in join dependency failure preservation."""

import pytest
from src.orchestrator.workflow import WorkflowManager, WorkflowStep, StepStatus


class TestWorkflowDependencyFanIn:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_fan_in_preserves_dependency_failure(self):
        """Steps that depend on a failed step should preserve the failure status."""
        wf = self.manager.create_workflow("fan_in_preserve", "test fan-in")
        step_a = WorkflowStep("step_a", lambda: (_ for _ in ()).throw(Exception("A failed")))
        step_b = WorkflowStep("step_b", lambda: "B ok", dependencies=[step_a.id])
        wf.add_step(step_a).add_step(step_b)

        result = self.manager.execute_workflow(wf.id)
        assert result is False, "Workflow should fail when upstream fails"
        assert step_a.status == StepStatus.FAILED, "Step A should be FAILED"
        assert "A failed" in step_a.error, "Step A error should be preserved"
        assert step_b.status == StepStatus.FAILED, "Step B should be FAILED due to dependency failure"
        assert "Skipped due to dependency failure" in step_b.error, (
            "Step B error should reference upstream failure"
        )
        assert "A failed" in step_b.error, "Step B error should preserve Step A's original error"
        assert wf.status == StepStatus.FAILED, "Workflow should end as FAILED"

    def test_fan_in_with_multiple_dependencies_one_fails(self):
        """When one upstream dependency fails, downstream steps still preserve that failure."""
        wf = self.manager.create_workflow("multi_dep_fail", "multi dep")
        step_a = WorkflowStep("step_a", lambda: "A ok")
        step_b = WorkflowStep("step_b", lambda: (_ for _ in ()).throw(Exception("B failed")))
        step_c = WorkflowStep("step_c", lambda: "C should not run",
                              dependencies=[step_a.id, step_b.id])
        wf.add_step(step_a).add_step(step_b).add_step(step_c)

        result = self.manager.execute_workflow(wf.id)
        assert result is False
        assert step_a.status == StepStatus.COMPLETED, "Step A should succeed"
        assert step_b.status == StepStatus.FAILED, "Step B should fail"
        assert step_c.status == StepStatus.FAILED, "Step C should be FAILED"
        assert "B failed" in step_c.error, "Step C error should preserve Step B's error"
        assert wf.status == StepStatus.FAILED

    def test_dependency_graph_deadlock_rejected(self):
        """Cyclic dependencies should be rejected."""
        wf = self.manager.create_workflow("deadlock", "circular deps")
        step_a = WorkflowStep("step_a", lambda: "A")
        step_b = WorkflowStep("step_b", lambda: "B", dependencies=[step_a.id])
        step_a.dependencies = [step_b.id]  # Create cycle
        wf.add_step(step_a).add_step(step_b)

        result = self.manager.execute_workflow(wf.id)
        assert result is False
        assert wf.status == StepStatus.PENDING, "Workflow should not transition from PENDING"
        # Deadlock prevents execution so status stays PENDING

    def test_no_fan_in_failure_all_pass(self):
        """When all upstream steps pass, the downstream step runs normally."""
        wf = self.manager.create_workflow("all_pass", "all pass")
        results = {}
        def make_handler(name, val):
            def h():
                results[name] = val
                return val
            return h

        step_a = WorkflowStep("step_a", make_handler("a", "ok_a"))
        step_b = WorkflowStep("step_b", make_handler("b", "ok_b"))
        step_c = WorkflowStep("step_c", make_handler("c", "ok_c"),
                              dependencies=[step_a.id, step_b.id])
        wf.add_step(step_a).add_step(step_b).add_step(step_c)

        result = self.manager.execute_workflow(wf.id)
        assert result is True, "Workflow should succeed"
        assert wf.status == StepStatus.COMPLETED
        assert results["a"] == "ok_a"
        assert results["b"] == "ok_b"
        assert results["c"] == "ok_c"
        assert step_c.status == StepStatus.COMPLETED

    def test_dependency_not_found_rejected(self):
        """Workflow execution should reject steps referencing non-existent dependencies."""
        wf = self.manager.create_workflow("bad_ref", "bad dep ref")
        step_a = WorkflowStep("step_a", lambda: "A", dependencies=["nonexistent-id"])
        wf.add_step(step_a)

        result = self.manager.execute_workflow(wf.id)
        assert result is False, "Workflow with bad dependency reference should fail"

    def test_fan_in_chain_preserves_cascade(self):
        """A chain A -> B -> C should cascade failure from A to C."""
        wf = self.manager.create_workflow("cascade", "cascade fail")
        step_a = WorkflowStep("step_a", lambda: (_ for _ in ()).throw(Exception("A err")))
        step_b = WorkflowStep("step_b", lambda: "B", dependencies=[step_a.id])
        step_c = WorkflowStep("step_c", lambda: "C", dependencies=[step_b.id])
        wf.add_step(step_a).add_step(step_b).add_step(step_c)

        result = self.manager.execute_workflow(wf.id)
        assert result is False
        assert step_a.status == StepStatus.FAILED
        assert "A err" in step_a.error
        assert step_b.status == StepStatus.FAILED
        assert "A err" in step_b.error
        assert step_c.status == StepStatus.FAILED
        assert "A err" in step_c.error, "Original failure should cascade all the way"


# 2026-05-24 test update for fan-in join dependency failure preservation

