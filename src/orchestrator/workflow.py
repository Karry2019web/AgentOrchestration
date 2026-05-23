"""Workflow Manager — Defines and executes multi-step agent workflows with branch-aware retry scoping."""

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
    def __init__(self, name: str, handler: Callable, retries: int = 0, timeout: int = 300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
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

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)


class ParallelBranch:
    """Represents a parallel execution branch within a workflow step.

    Each branch gets a unique attempt_id for retry counter isolation,
    ensuring one branch's retries don't consume the retry budget of
    another branch.
    """

    def __init__(self, name: str, handler: Callable, retries: int = 0):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class RetryScope:
    """Encapsulates attempt-scoped retry state for a single workflow execution branch.

    Each RetryScope instance is tied to one execution path (one attempt),
    so retry counters are naturally isolated across parallel branches.
    """

    def __init__(self, task_id: str, attempt_id: str, max_retries: int = 3):
        self.task_id = task_id
        self.attempt_id = attempt_id
        self.max_retries = max_retries
        self._attempt_count = 0

    @property
    def attempt(self) -> int:
        return self._attempt_count

    def record_attempt(self) -> int:
        self._attempt_count += 1
        return self._attempt_count

    def can_retry(self) -> bool:
        return self._attempt_count < self.max_retries

    def remaining(self) -> int:
        return max(0, self.max_retries - self._attempt_count)


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

    def execute_parallel_branch(
        self,
        branch: ParallelBranch,
        task_id: str,
        attempt_id: str,
        max_retries: int = 3,
    ) -> bool:
        """Execute a single parallel branch with attempt-scoped retries.

        Each call creates its own RetryScope with the given attempt_id,
        ensuring retry counters are isolated across parallel branches.

        Args:
            branch: The parallel branch to execute.
            task_id: Task ID for retry tracking.
            attempt_id: Unique ID per attempt for counter isolation.
            max_retries: Maximum retries for this branch.

        Returns:
            True if the branch completed (possibly after retries), False if failed.
        """
        scope = RetryScope(task_id, attempt_id, max_retries)
        branch.status = StepStatus.RUNNING

        while scope.can_retry():
            scope.record_attempt()
            try:
                result = branch.handler()
                branch.result = result
                branch.status = StepStatus.COMPLETED
                return True
            except Exception as e:
                branch.error = str(e)
                branch.status = StepStatus.FAILED

        return False
