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
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    COMPENSATED = "compensated"


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: int = 300, compensate: Optional[Callable] = None):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.compensate = compensate
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
        completed_steps: List[WorkflowStep] = []

        for step in workflow.steps:
            # Block downstream after partial rollback — skip remaining steps
            if workflow.status in (StepStatus.ROLLING_BACK, StepStatus.ROLLED_BACK):
                step.status = StepStatus.SKIPPED
                continue

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
                completed_steps.append(step)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                # Execute compensating actions for completed steps in reverse
                self._rollback(workflow, completed_steps, step)
                workflow.status = StepStatus.ROLLED_BACK
                return False

        workflow.status = StepStatus.COMPLETED
        return True

    def _rollback(self, workflow: "Workflow", completed_steps: List[WorkflowStep], failed_step: "WorkflowStep") -> None:
        """Execute compensating actions for completed steps in reverse order."""
        workflow.status = StepStatus.ROLLING_BACK
        for step in reversed(completed_steps):
            if step.compensate:
                try:
                    step.compensate(step.result)
                    step.status = StepStatus.COMPENSATED
                except Exception as e:
                    step.error = str(e)
                    step.status = StepStatus.ROLLED_BACK
            else:
                step.status = StepStatus.ROLLED_BACK
