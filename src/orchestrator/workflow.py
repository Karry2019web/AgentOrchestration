"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class SensitiveInput:
    """Declares a named input parameter as sensitive, requiring explicit opt-in.

    Steps that accept sensitive data (API keys, credentials, PII) must
    declare each sensitive input explicitly. The workflow input schema
    validator rejects any step that passes sensitive data through a
    non-declared parameter, preventing accidental data leaks.
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description


class WorkflowInputSchema:
    """Schema validator for workflow step inputs.

    Enforces that:
    1. All sensitive input parameters are explicitly declared per step.
    2. Steps do not receive undeclared sensitive data at binding time.
    """

    def __init__(self):
        self._step_sensitive_inputs: Dict[str, Set[str]] = {}

    def declare_sensitive_input(self, step_name: str, input_name: str) -> None:
        """Mark *input_name* as a sensitive parameter for *step_name*."""
        if step_name not in self._step_sensitive_inputs:
            self._step_sensitive_inputs[step_name] = set()
        self._step_sensitive_inputs[step_name].add(input_name)

    def declare_sensitive_inputs(self, step_name: str, *inputs: SensitiveInput) -> None:
        """Declare multiple sensitive inputs for a step at once."""
        for inp in inputs:
            self.declare_sensitive_input(step_name, inp.name)

    def validate(self, step_name: str, inputs: Dict[str, Any]) -> None:
        """Validate that all propagated inputs for *step_name* are safe.

        Raises ``ValueError`` if any input value looks sensitive (string
        longer than 32 chars without whitespace, or matching common
        credential patterns) but has not been explicitly declared.
        """
        declared = self._step_sensitive_inputs.get(step_name, set())
        _SENSITIVE_PATTERNS = (
            "api_key", "apikey", "secret", "token",
            "password", "passwd", "credential", "auth", "bearer",
            "private_key", "access_key", "pat_", "ghp_", "sk-",
        )

        for key, value in inputs.items():
            if key in declared:
                continue
            if isinstance(value, str) and len(value) > 32 and " " not in value:
                raise ValueError(
                    f"Step '{step_name}' receives undeclared sensitive input "
                    f"'{key}'. Declare it via declare_sensitive_input() or "
                    f"SensitiveInput() before binding."
                )
            if isinstance(value, str):
                lower_val = value.lower()
                for pattern in _SENSITIVE_PATTERNS:
                    if lower_val.startswith(pattern):
                        raise ValueError(
                            f"Step '{step_name}' receives undeclared sensitive input "
                            f"'{key}' (matches pattern '{pattern}'). Declare it via "
                            f"declare_sensitive_input() or SensitiveInput()."
                        )

    def validate_workflow(self, workflow: "Workflow", step_inputs: Dict[str, Dict[str, Any]]) -> None:
        """Validate all step inputs for a workflow at registration time."""
        for step in workflow.steps:
            inputs = step_inputs.get(step.name, {})
            self.validate(step.name, inputs)


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: int = 300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None
        self._sensitive_inputs: Set[str] = set()

    def declare_sensitive(self, *names: str) -> "WorkflowStep":
        """Explicitly mark step input parameters as sensitive."""
        self._sensitive_inputs.update(names)
        return self


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.input_schema = WorkflowInputSchema()

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def validate_bindings(self, step_inputs: Dict[str, Dict[str, Any]]) -> None:
        """Validate all step input bindings before workflow execution.

        Raises ``ValueError`` if any step receives undeclared sensitive data.
        Call this at registration time (pre-dispatch) to catch bad graphs
        before any step starts executing.
        """
        self.input_schema.validate_workflow(self, step_inputs)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def register_workflow(self, workflow: Workflow, step_inputs: Optional[Dict[str, Dict[str, Any]]] = None) -> str:
        """Register a workflow and validate its input bindings upfront.

        Performs input schema validation at registration time so invalid
        bindings are caught before any step executes.
        """
        if step_inputs is not None:
            workflow.validate_bindings(step_inputs)
        self._workflows[workflow.id] = workflow
        return workflow.id

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str, step_inputs: Optional[Dict[str, Dict[str, Any]]] = None) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        if step_inputs is not None:
            try:
                workflow.validate_bindings(step_inputs)
            except ValueError:
                workflow.status = StepStatus.FAILED
                raise

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED
                return False

        workflow.status = StepStatus.COMPLETED
        return True
