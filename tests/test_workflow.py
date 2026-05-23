import pytest
from src.orchestrator.workflow import (
    Workflow,
    WorkflowStep,
    WorkflowManager,
    StepStatus,
)


class TestWorkflowDependencies:
    def setup_method(self):
        self.manager = WorkflowManager()

    def test_add_step_with_dependencies(self):
        """Verify fan-in join: a step can depend on multiple predecessors."""
        workflow = Workflow("fan-in-test")
        step_a = WorkflowStep("step_a", lambda: "result_a")
        step_b = WorkflowStep("step_b", lambda: "result_b")
        step_c = WorkflowStep("step_c", lambda: "result_c")

        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step_with_dependencies(step_c, [step_a, step_b])

        assert step_a.id in step_c.depends_on
        assert step_b.id in step_c.depends_on
        assert len(step_c.depends_on) == 2

    def test_validate_missing_dependency(self):
        """Reject steps that reference nonexistent step IDs."""
        workflow = Workflow("missing-dep")
        step_a = WorkflowStep("step_a", lambda: None)
        step_a.depends_on.add("nonexistent-id")
        workflow.add_step(step_a)

        errors = workflow.validate_dependencies()
        assert len(errors) == 1
        assert "unknown step id" in errors[0]

    def test_validate_circular_dependency(self):
        """Reject workflows with circular dependencies."""
        workflow = Workflow("circular")
        step_a = WorkflowStep("step_a", lambda: None)
        step_b = WorkflowStep("step_b", lambda: None)
        step_a.depends_on.add(step_b.id)
        step_b.depends_on.add(step_a.id)
        workflow.add_step(step_a)
        workflow.add_step(step_b)

        errors = workflow.validate_dependencies()
        assert len(errors) >= 1
        assert "circular" in errors[0].lower()

    def test_validate_valid_dag(self):
        """Accept a valid DAG without errors."""
        workflow = Workflow("valid-dag")
        step_a = WorkflowStep("step_a", lambda: None)
        step_b = WorkflowStep("step_b", lambda: None)
        step_c = WorkflowStep("step_c", lambda: None)

        workflow.add_step(step_a)
        workflow.add_step_with_dependencies(step_b, [step_a])
        workflow.add_step_with_dependencies(step_c, [step_a, step_b])

        errors = workflow.validate_dependencies()
        assert errors == []

    def test_execute_fan_in_join_success(self):
        """All dependencies succeed, downstream step runs."""
        workflow = Workflow("fan-in-success")
        results = []

        step_a = WorkflowStep("step_a", lambda: results.append("a"))
        step_b = WorkflowStep("step_b", lambda: results.append("b"))
        step_c = WorkflowStep("step_c", lambda: results.append("c"))

        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step_with_dependencies(step_c, [step_a, step_b])

        assert self.manager.register_workflow(workflow)
        assert self.manager.execute_workflow(workflow.id)

        assert step_c.status == StepStatus.COMPLETED
        assert workflow.status == StepStatus.COMPLETED

    def test_execute_fan_in_join_dependency_failure(self):
        """When a dependency fails, downstream steps are skipped preserving failure status."""
        workflow = Workflow("fan-in-failure")
        results = []

        def failing_handler():
            raise ValueError("Dependency failure")

        step_a = WorkflowStep("step_a", lambda: results.append("a"))
        step_b = WorkflowStep("step_b", failing_handler)
        step_c = WorkflowStep("step_c", lambda: results.append("c"))

        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step_with_dependencies(step_c, [step_a, step_b])

        assert self.manager.register_workflow(workflow)
        result = self.manager.execute_workflow(workflow.id)
        assert not result  # workflow should fail

        assert step_a.status == StepStatus.COMPLETED
        assert step_b.status == StepStatus.FAILED
        assert step_c.status == StepStatus.SKIPPED
        assert workflow.status == StepStatus.FAILED

    def test_execute_fan_in_join_single_failure_preserves_status(self):
        """Fan-in join: only the dependent step's failure is preserved."""
        workflow = Workflow("single-failure")
        results = []

        step_a = WorkflowStep("step_a", lambda: results.append("a"))
        step_b = WorkflowStep("step_b", lambda: (_ for _ in ()).throw(ValueError("step_b failed")))
        step_c = WorkflowStep("step_c", lambda: results.append("c"))

        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step_with_dependencies(step_c, [step_a, step_b])

        assert self.manager.register_workflow(workflow)
        result = self.manager.execute_workflow(workflow.id)
        assert not result

        assert step_a.status == StepStatus.COMPLETED
        assert step_b.status == StepStatus.FAILED
        assert step_c.status == StepStatus.SKIPPED
        assert step_b.error is not None
        assert "failed" in step_b.error

    def test_register_rejects_invalid_workflow(self):
        """register_workflow validates and rejects invalid dependency graphs."""
        workflow = Workflow("invalid-registration")
        step_a = WorkflowStep("step_a", lambda: None)
        step_b = WorkflowStep("step_b", lambda: None)
        step_b.depends_on.add("missing-id")
        workflow.add_step(step_a)
        workflow.add_step(step_b)

        assert not self.manager.register_workflow(workflow)
        assert self.manager.get_workflow(workflow.id) is None

    def test_sequential_steps_still_work(self):
        """Backward compatibility: steps without dependencies execute sequentially."""
        workflow = Workflow("sequential")
        results = []

        step_a = WorkflowStep("step_a", lambda: results.append("a"))
        step_b = WorkflowStep("step_b", lambda: results.append("b"))
        step_c = WorkflowStep("step_c", lambda: results.append("c"))

        workflow.add_step(step_a)
        workflow.add_step(step_b)
        workflow.add_step(step_c)

        assert self.manager.register_workflow(workflow)
        assert self.manager.execute_workflow(workflow.id)
        assert results == ["a", "b", "c"]
        assert workflow.status == StepStatus.COMPLETED


class TestWorkflowManagerRegistration:
    def test_register_workflow_passes_validation(self):
        manager = WorkflowManager()
        wf = Workflow("test")
        wf.add_step(WorkflowStep("single", lambda: None))
        assert manager.register_workflow(wf)
        assert manager.get_workflow(wf.id) is not None

    def test_list_workflows_after_register(self):
        manager = WorkflowManager()
        wf1 = Workflow("alpha")
        wf2 = Workflow("beta")
        wf1.add_step(WorkflowStep("s1", lambda: None))
        wf2.add_step(WorkflowStep("s2", lambda: None))
        manager.register_workflow(wf1)
        manager.register_workflow(wf2)
        assert len(manager.list_workflows()) == 2
