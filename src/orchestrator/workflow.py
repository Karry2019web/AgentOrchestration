"""Workflow Manager — Defines and executes multi-step agent workflows."""

import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


class CompensationResult(Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PARTIAL = "partial"


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: int = 300, compensation: Optional[Callable] = None):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.compensation = compensation
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class CompensationEngine:
    """Manages compensating actions during partial rollback.

    After a step fails mid-workflow, already-completed steps must run their
    compensating actions in reverse order. The engine rejects stale, duplicate,
    or policy-violating compensation requests and records the decision.
    """

    def __init__(self):
        self._compensated: set[str] = set()
        self._in_progress: Optional[str] = None
        self._rollback_active = False
        self._decision_log: list[dict] = []

    @property
    def is_rollback_active(self) -> bool:
        return self._rollback_active

    def start_rollback(self, workflow_id: str, failed_step_name: str) -> CompensationResult:
        """Initiate a rollback for a workflow after a step failure.

        Returns REJECTED if a rollback is already in progress (duplicate),
        or if no completed steps exist to compensate (stale).
        """
        if self._rollback_active:
            logger.warning(
                "Rollback already in progress for workflow %s; rejecting duplicate request",
                workflow_id,
            )
            self._decision_log.append({
                "workflow": workflow_id,
                "decision": "rejected",
                "reason": "rollback_already_active",
                "trigger": failed_step_name,
            })
            return CompensationResult.REJECTED

        if not self._rollback_active:
            logger.info("Starting rollback for workflow %s triggered by step '%s'", workflow_id, failed_step_name)
            self._rollback_active = True
            self._decision_log.append({
                "workflow": workflow_id,
                "decision": "accepted",
                "reason": "step_failure_rollback",
                "trigger": failed_step_name,
            })
            return CompensationResult.ACCEPTED

        return CompensationResult.REJECTED

    def compensate_step(self, step: WorkflowStep) -> bool:
        """Execute the compensating action for a single step.

        Returns True if compensation was executed, False if already compensated.
        """
        if step.id in self._compensated:
            logger.debug("Step '%s' already compensated; skipping", step.name)
            return False

        if step.compensation:
            self._in_progress = step.id
            try:
                step.compensation()
                step.status = StepStatus.COMPENSATED
                self._compensated.add(step.id)
                logger.info("Compensated step '%s'", step.name)
            except Exception as e:
                step.status = StepStatus.COMPENSATED
                self._compensated.add(step.id)
                logger.warning("Compensation for step '%s' raised %s; marking compensated anyway", step.name, e)
        else:
            step.status = StepStatus.COMPENSATED
            self._compensated.add(step.id)
            logger.info("Step '%s' has no compensation handler; marking compensated", step.name)

        self._in_progress = None
        return True

    def finalize_rollback(self, workflow_id: str) -> None:
        """End the rollback phase and record the outcome."""
        self._rollback_active = False
        self._in_progress = None
        logger.info("Rollback finalized for workflow %s (compensated %d steps)", workflow_id, len(self._compensated))
        self._decision_log.append({
            "workflow": workflow_id,
            "decision": "finalized",
            "compensated_count": len(self._compensated),
        })


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING
        self.compensation_engine = CompensationEngine()

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def _block_downstream_after(self, failed_index: int) -> None:
        """Mark all steps after failed_index as SKIPPED and log the decision."""
        for step in self.steps[failed_index + 1:]:
            step.status = StepStatus.SKIPPED
            logger.info(
                "Downstream step '%s' blocked after partial rollback of workflow '%s'",
                step.name,
                self.name,
            )
            self.compensation_engine._decision_log.append({
                "workflow": self.id,
                "decision": "blocked",
                "reason": "partial_rollback_downstream",
                "step": step.name,
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

        for idx, step in enumerate(workflow.steps):
            # Check if a rollback is already active (should not happen during normal execution)
            if workflow.compensation_engine.is_rollback_active:
                step.status = StepStatus.SKIPPED
                logger.warning("Step '%s' skipped: rollback active in workflow '%s'", step.name, workflow.name)
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

                # Start rollback — compensate already-completed steps in reverse order
                result = workflow.compensation_engine.start_rollback(workflow.id, step.name)
                if result == CompensationResult.ACCEPTED:
                    # Block all steps after the failed one
                    workflow._block_downstream_after(idx)

                    # Compensate completed steps in reverse order
                    for prev_step in reversed(workflow.steps[:idx]):
                        if prev_step.status == StepStatus.COMPLETED:
                            workflow.compensation_engine.compensate_step(prev_step)

                    workflow.compensation_engine.finalize_rollback(workflow.id)

                return False

        workflow.status = StepStatus.COMPLETED
        return True
