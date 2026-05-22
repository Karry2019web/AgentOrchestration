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


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: int = 300,
        condition: Optional[Callable[[], bool]] = None,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.condition = condition
        self.retries = retries
        self.timeout = timeout
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
        self.audit_log: List[Dict[str, str]] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def _record_audit(
        self,
        decision: str,
        reason: str,
        step_id: str = "",
        step_name: str = "",
    ) -> None:
        self.audit_log.append({
            "decision": decision,
            "reason": reason,
            "step_id": step_id,
            "step_name": step_name,
        })


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
            decision = self._check_step_condition(workflow, step)
            if decision is None:
                return False
            if not decision:
                continue

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

    def _snapshot_workflow(self, workflow: Workflow) -> Dict[str, Any]:
        return {
            "status": workflow.status,
            "step_states": {
                step.id: {
                    "status": step.status,
                    "result": step.result,
                    "error": step.error,
                }
                for step in workflow.steps
            },
        }

    def _restore_workflow(self, workflow: Workflow, snapshot: Dict[str, Any]) -> None:
        workflow.status = snapshot["status"]
        for step in workflow.steps:
            state = snapshot["step_states"].get(step.id)
            if state:
                step.status = state["status"]
                step.result = state["result"]
                step.error = state["error"]

    def _check_step_condition(self, workflow: Workflow, step: WorkflowStep) -> bool:
        if step.condition is None:
            return True

        before = self._snapshot_workflow(workflow)
        try:
            result = step.condition()
        except Exception as e:
            self._restore_workflow(workflow, before)
            step.status = StepStatus.FAILED
            step.error = f"workflow condition raised: {e}"
            workflow.status = StepStatus.FAILED
            workflow._record_audit("rejected", f"condition raised: {e}", step.id, step.name)
            return None  # None = reject, stop the workflow

        after = self._snapshot_workflow(workflow)
        if before != after:
            self._restore_workflow(workflow, before)
            step.status = StepStatus.FAILED
            step.error = "condition attempted workflow lifecycle side effects"
            workflow.status = StepStatus.FAILED
            workflow._record_audit(
                "rejected", "condition lifecycle side effects detected",
                step.id, step.name,
            )
            return None  # None = reject, stop the workflow

        if not isinstance(result, bool):
            self._restore_workflow(workflow, before)
            step.status = StepStatus.FAILED
            step.error = "condition must return bool"
            workflow.status = StepStatus.FAILED
            workflow._record_audit(
                "rejected", f"condition returned {type(result).__name__}, expected bool",
                step.id, step.name,
            )
            return None  # None = reject, stop the workflow

        if not result:
            step.status = StepStatus.SKIPPED
            workflow._record_audit(
                "skipped", "condition evaluated to false",
                step.id, step.name,
            )
            return False

        workflow._record_audit(
            "accepted", "condition evaluated to true",
            step.id, step.name,
        )
        return True
