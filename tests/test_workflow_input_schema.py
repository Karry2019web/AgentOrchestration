"""Tests for workflow input schema — sensitive input declarations."""

import pytest
from src.orchestrator.workflow import (
    SensitiveInput,
    WorkflowInputSchema,
    WorkflowStep,
    Workflow,
    WorkflowManager,
)


class TestSensitiveInput:
    def test_create_sensitive_input(self):
        inp = SensitiveInput("api_key", "The API key for external service")
        assert inp.name == "api_key"
        assert inp.description == "The API key for external service"

    def test_sensitive_input_default_description(self):
        inp = SensitiveInput("token")
        assert inp.name == "token"
        assert inp.description == ""


class TestWorkflowInputSchema:
    def setup_method(self):
        self.schema = WorkflowInputSchema()

    def test_declare_sensitive_input_accepts_declared(self):
        self.schema.declare_sensitive_input("fetch_data", "api_key")
        # Should not raise
        self.schema.validate("fetch_data", {"api_key": "my-secret-key-that-is-long"})

    def test_rejects_undeclared_long_string(self):
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            self.schema.validate("fetch_data", {"credential": "a" * 40})

    def test_accepts_short_string_without_declaration(self):
        # Short strings (< 32 chars) are not flagged as sensitive
        self.schema.validate("fetch_data", {"name": "bob"})

    def test_rejects_undeclared_token_pattern(self):
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            self.schema.validate("api_call", {"auth": "ghp_xxxxxxxxxxxxxxxxxxxx"})

    def test_rejects_undeclared_secret(self):
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            self.schema.validate("auth_step", {"credential": "sk-proj-xxxxxxxxxx"})

    def test_accepts_multiple_declared_inputs(self):
        self.schema.declare_sensitive_inputs(
            "process",
            SensitiveInput("api_key"),
            SensitiveInput("secret"),
        )
        self.schema.validate("process", {"api_key": "long-secret-value", "secret": "another-long-value"})

    def test_rejects_undeclared_in_mixed_inputs(self):
        self.schema.declare_sensitive_input("step1", "api_key")
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            self.schema.validate("step1", {"api_key": "declared-ok", "password": "hunter2-but-long-secret"})

    def test_different_steps_independent_declarations(self):
        self.schema.declare_sensitive_input("good_step", "token")
        self.schema.validate("good_step", {"token": "some-long-token-that-is-sensitive"})
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            self.schema.validate("bad_step", {"token": "some-long-token-that-is-sensitive"})


class TestWorkflowStepSensitiveDeclaration:
    def test_declare_sensitive_on_step(self):
        step = WorkflowStep("fetch", lambda: None)
        step.declare_sensitive("api_key", "token")
        assert "api_key" in step._sensitive_inputs
        assert "token" in step._sensitive_inputs


class TestWorkflowValidation:
    def test_validate_bindings_passes_with_declared(self):
        workflow = Workflow("test")
        step = WorkflowStep("fetch", lambda: None)
        workflow.add_step(step)

        step.declare_sensitive("api_key")
        workflow.input_schema.declare_sensitive_input("fetch", "api_key")

        # Should not raise
        workflow.validate_bindings({"fetch": {"api_key": "some-long-secret-value"}})

    def test_validate_bindings_rejects_undeclared(self):
        workflow = Workflow("test")
        step = WorkflowStep("fetch", lambda: None)
        workflow.add_step(step)

        with pytest.raises(ValueError, match="undeclared sensitive input"):
            workflow.validate_bindings({"fetch": {"token": "ghp_long_secret_value_here"}})

    def test_validate_bindings_empty_inputs(self):
        workflow = Workflow("test")
        step = WorkflowStep("fetch", lambda: None)
        workflow.add_step(step)

        # Empty inputs should pass — nothing to validate
        workflow.validate_bindings({"fetch": {}})

    def test_validate_bindings_no_inputs_for_step(self):
        workflow = Workflow("test")
        step = WorkflowStep("fetch", lambda: None)
        workflow.add_step(step)

        # Step not in bindings dict — no inputs to check
        workflow.validate_bindings({})


class TestWorkflowManagerRegistration:
    def test_register_without_validation(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_step(WorkflowStep("step1", lambda: None))

        wf_id = manager.register_workflow(workflow)
        assert manager.get_workflow(wf_id) is not None

    def test_register_with_valid_inputs(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        step = WorkflowStep("step1", lambda: None)
        step.declare_sensitive("api_key")
        workflow.add_step(step)
        workflow.input_schema.declare_sensitive_input("step1", "api_key")

        wf_id = manager.register_workflow(workflow, {"step1": {"api_key": "long-key-value"}})
        assert manager.get_workflow(wf_id) is not None

    def test_register_rejects_invalid_inputs(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_step(WorkflowStep("step1", lambda: None))

        with pytest.raises(ValueError, match="undeclared sensitive input"):
            manager.register_workflow(workflow, {"step1": {"secret": "a" * 40}})

    def test_execute_with_valid_inputs(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        step = WorkflowStep("step1", lambda: "done")
        step.declare_sensitive("api_key")
        workflow.add_step(step)
        workflow.input_schema.declare_sensitive_input("step1", "api_key")

        wf_id = manager.register_workflow(workflow)
        result = manager.execute_workflow(wf_id, {"step1": {"api_key": "long-key-value"}})
        assert result is True

    def test_execute_rejects_invalid_inputs(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_step(WorkflowStep("step1", lambda: "done"))

        wf_id = manager.register_workflow(workflow)
        with pytest.raises(ValueError, match="undeclared sensitive input"):
            manager.execute_workflow(wf_id, {"step1": {"token": "ghp_long_secret_value"}})

    def test_execute_rejected_input_sets_failed_status(self):
        manager = WorkflowManager()
        workflow = Workflow("test")
        workflow.add_step(WorkflowStep("step1", lambda: "done"))

        wf_id = manager.register_workflow(workflow)
        try:
            manager.execute_workflow(wf_id, {"step1": {"secret": "a" * 40}})
        except ValueError:
            pass
        assert workflow.status.value == "failed"
