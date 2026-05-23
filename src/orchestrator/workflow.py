"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TimeoutUnit(Enum):
    """Supported timeout units for workflow steps."""
    SECONDS = "seconds"
    MINUTES = "minutes"
    HOURS = "hours"
    MILLISECONDS = "milliseconds"

    def to_seconds(self, value: int) -> int:
        if self == TimeoutUnit.SECONDS:
            return value
        elif self == TimeoutUnit.MINUTES:
            return value * 60
        elif self == TimeoutUnit.HOURS:
            return value * 3600
        elif self == TimeoutUnit.MILLISECONDS:
            return value // 1000
        return value


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: int = 300, timeout_unit: TimeoutUnit = TimeoutUnit.SECONDS):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.timeout_unit = timeout_unit
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        # Validate: reject conflicting timeout units across steps
        if self.steps and step.timeout_unit:
            first_unit = self.steps[0].timeout_unit
            if first_unit and step.timeout_unit and first_unit != step.timeout_unit:
                raise ValueError(
                    f"Conflicting timeout unit: step '{step.name}' uses "
                    f"'{step.timeout_unit.value}', but existing steps use "
                    f"'{first_unit.value}'. All steps in a workflow must "
                    f"share the same timeout unit."
                )
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id: str) -> Optional[Workflow]:
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> List[Workflow]:
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id: str) -> bool:
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id: str) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

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
