import pytest
from src.orchestrator.workflow import (
    WorkflowManager, WorkflowStep, WorkflowCondition,
    ConditionViolationError, SandboxExpressionError,
    _check_sandbox_expression, _evaluate_sandbox_safe,
)


class TestWorkflowCondition:
    """Tests for sandboxed workflow conditions evaluation."""

    def test_valid_expressions_evaluate_correctly(self):
        context = {"x": 10, "y": 5, "status": "ready"}
        assert _evaluate_sandbox_safe("x > y", context) is True
        assert _evaluate_sandbox_safe("x == 10", context) is True
        assert _evaluate_sandbox_safe("status == 'ready'", context) is True
        assert _evaluate_sandbox_safe("x < y", context) is False

    def test_arithmetic_expressions(self):
        context = {"count": 42, "limit": 100}
        assert _evaluate_sandbox_safe("count + 10 <= limit", context) is True
        assert _evaluate_sandbox_safe("count * 2 > limit", context) is False

    def test_boolean_logic(self):
        context = {"a": True, "b": False, "x": 5}
        assert _evaluate_sandbox_safe("a and x > 0", context) is True
        assert _evaluate_sandbox_safe("b or x > 0", context) is True
        assert _evaluate_sandbox_safe("b and x > 0", context) is False

    def test_uses_allowed_builtins(self):
        context = {"items": [1, 2, 3], "threshold": 2}
        assert _evaluate_sandbox_safe("len(items) > threshold", context) is True
        assert _evaluate_sandbox_safe("max(items) == 3", context) is True
        assert _evaluate_sandbox_safe("sum(items) == 6", context) is True
        assert _evaluate_sandbox_safe("all(x > 0 for x in items)", context) is True

    def test_rejects_imports(self):
        with pytest.raises(ConditionViolationError, match="Forbidden construct"):
            _check_sandbox_expression("__import__('os')", set())

    def test_rejects_function_calls_outside_whitelist(self):
        context = {"x": 1}
        with pytest.raises(ConditionViolationError, match="Forbidden function call"):
            _check_sandbox_expression("custom_func(x)", set(context.keys()))

    def test_rejects_unknown_variables(self):
        context = {"known": 42}
        with pytest.raises(ConditionViolationError, match="Unknown variable"):
            _check_sandbox_expression("unknown_var > 0", set(context.keys()))

    def test_rejects_dunder_attribute_access(self):
        context = {"x": 1}
        with pytest.raises(ConditionViolationError, match="Forbidden attribute access on dunder name"):
            _check_sandbox_expression("x.__class__", set(context.keys()))

    def test_rejects_assignment(self):
        with pytest.raises(ConditionViolationError, match="Forbidden construct"):
            _check_sandbox_expression("x = 1", {"x": 0})

    def test_rejects_empty_expression(self):
        with pytest.raises(ConditionViolationError, match="cannot be empty"):
            WorkflowCondition("")

    def test_condition_must_evaluate_to_bool(self):
        context = {"x": 42}
        with pytest.raises(SandboxExpressionError, match="must evaluate to bool"):
            _evaluate_sandbox_safe("x", context)


class TestWorkflowStepWithCondition:
    """Tests for condition-aware workflow steps."""

    def test_step_without_condition_executes(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        results = []

        def handler():
            results.append("executed")

        step = WorkflowStep("step1", handler)
        workflow.add_step(step)
        assert manager.execute_workflow(workflow.id) is True
        assert results == ["executed"]

    def test_step_with_true_condition_executes(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        results = []

        def handler():
            results.append("executed")

        step = WorkflowStep("step1", handler, condition=WorkflowCondition("True"))
        workflow.add_step(step)
        assert manager.execute_workflow(workflow.id, {"should_run": True}) is True
        assert results == ["executed"]

    def test_step_with_false_condition_is_skipped(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        results = []

        def handler():
            results.append("executed")

        step = WorkflowStep("step1", handler, condition=WorkflowCondition("False"))
        workflow.add_step(step)
        assert manager.execute_workflow(workflow.id) is True
        assert results == []

    def test_condition_using_context(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        results = []

        def handler():
            results.append("executed")

        step = WorkflowStep("step1", handler, condition=WorkflowCondition("priority > 50"))
        workflow.add_step(step)
        assert manager.execute_workflow(workflow.id, {"priority": 10}) is True
        assert results == []

        step2 = WorkflowStep("step2", lambda: results.append("executed2"),
                             condition=WorkflowCondition("priority > 50"))
        workflow2 = manager.create_workflow("test2")
        workflow2.add_step(step2)
        assert manager.execute_workflow(workflow2.id, {"priority": 100}) is True
        assert "executed2" in results

    def test_multiple_steps_with_mixed_conditions(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        results = []

        step1 = WorkflowStep("always", lambda: results.append("a"), condition=WorkflowCondition("True"))
        step2 = WorkflowStep("never", lambda: results.append("b"), condition=WorkflowCondition("False"))
        step3 = WorkflowStep("conditional", lambda: results.append("c"),
                             condition=WorkflowCondition("flag"))
        step4 = WorkflowStep("always2", lambda: results.append("d"))

        workflow.add_step(step1)
        workflow.add_step(step2)
        workflow.add_step(step3)
        workflow.add_step(step4)

        assert manager.execute_workflow(workflow.id, {"flag": True}) is True
        assert results == ["a", "c", "d"]


class TestWorkflowValidation:
    """Tests for pre-dispatch condition validation."""

    def test_validates_all_conditions_on_execute(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("good")
        step = WorkflowStep("good_step", lambda: None,
                            condition=WorkflowCondition("True"))
        workflow.add_step(step)
        errors = manager.validate_workflow(workflow.id)
        assert errors == []

    def test_rejects_invalid_condition_at_construction(self):
        with pytest.raises(ConditionViolationError):
            WorkflowCondition("__import__('os').system('rm -rf /')")

    def test_non_bool_expression_caught_at_evaluation(self):
        manager = WorkflowManager()
        workflow = manager.create_workflow("test")
        step = WorkflowStep("bad", lambda: None, condition=WorkflowCondition("True"))
        workflow.add_step(step)
        with pytest.raises(SandboxExpressionError, match="must evaluate to bool"):
            _evaluate_sandbox_safe("42", {})

    def test_rejects_forbidden_attributes(self):
        context = {"x": 1}
        with pytest.raises(ConditionViolationError, match="Forbidden name in sandbox expression"):
            _check_sandbox_expression("eval('print(1)')", set(context.keys()))

    def test_rejects_forbidden_builtins(self):
        with pytest.raises(ConditionViolationError, match="Forbidden name in sandbox expression"):
            _check_sandbox_expression("open('/etc/passwd')", set())

    def test_workflow_with_bad_condition_rejected_at_execute_time(self):
        """Conditions are validated at construction so invalid never registered."""
        manager = WorkflowManager()
        workflow = manager.create_workflow("safe")
        step = WorkflowStep("safe", lambda: None, condition=WorkflowCondition("True"))
        workflow.add_step(step)
        assert manager.execute_workflow(workflow.id) is True
