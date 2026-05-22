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


class ArtifactRetentionPolicy:
    """Declares a retention policy for workflow artifacts.

    Policies enforce that artifacts are cleaned up on a schedule
    and that invalid retention configurations are caught at
    registration time rather than during execution.
    """

    VALID_PERIODS = ("1h", "6h", "24h", "7d", "30d", "90d", "forever")

    def __init__(self, max_age: str = "30d", auto_cleanup: bool = True):
        if max_age not in self.VALID_PERIODS:
            raise ValueError(
                f"Invalid retention period '{max_age}'. Must be one of: "
                f"{', '.join(self.VALID_PERIODS)}"
            )
        self.max_age = max_age
        self.auto_cleanup = auto_cleanup

    def __repr__(self) -> str:
        return f"ArtifactRetentionPolicy(max_age='{self.max_age}', auto_cleanup={self.auto_cleanup})"


class ArtifactRetentionValidator:
    """Validates artifact retention policies at workflow registration time.

    Ensures that:
    1. All artifact retention policies use valid periods.
    2. Policies with auto_cleanup=True have a finite max_age (not "forever").
    3. Conflicting policies (same artifact type, different retention) are rejected.
    """

    def __init__(self):
        self._policies: Dict[str, ArtifactRetentionPolicy] = {}

    def add_policy(self, artifact_type: str, policy: ArtifactRetentionPolicy) -> None:
        """Register a retention policy for an artifact type.

        Raises ``ValueError`` if auto_cleanup is enabled with 'forever'
        retention, or if a conflicting policy already exists.
        """
        if policy.auto_cleanup and policy.max_age == "forever":
            raise ValueError(
                f"Artifact type '{artifact_type}' has auto_cleanup=True but "
                f"max_age='forever'. Cleanup requires a finite retention period."
            )

        if artifact_type in self._policies:
            existing = self._policies[artifact_type]
            if existing.max_age != policy.max_age:
                raise ValueError(
                    f"Conflicting retention policies for artifact type "
                    f"'{artifact_type}': existing='{existing.max_age}', "
                    f"new='{policy.max_age}'. Use consistent retention periods."
                )

        self._policies[artifact_type] = policy

    def validate_cleanup_schedule(self) -> None:
        """Validate that all registered policies can be scheduled for cleanup.

        Raises ``ValueError`` if any policy with auto_cleanup has an
        invalid or unparseable retention period.
        """
        for artifact_type, policy in self._policies.items():
            if policy.auto_cleanup and policy.max_age not in self.VALID_PERIODS:
                raise ValueError(
                    f"Artifact type '{artifact_type}' has auto_cleanup=True but "
                    f"unrecognized max_age '{policy.max_age}'. "
                    f"Valid periods: {', '.join(self.VALID_PERIODS)}"
                )

    def list_policies(self) -> Dict[str, ArtifactRetentionPolicy]:
        return dict(self._policies)

    # Shared valid periods for validation
    VALID_PERIODS = ArtifactRetentionPolicy.VALID_PERIODS


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
        self.artifact_retention = ArtifactRetentionValidator()

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def add_artifact_retention_policy(self, artifact_type: str, policy: ArtifactRetentionPolicy) -> None:
        """Register an artifact retention policy for validation at registration time."""
        self.artifact_retention.add_policy(artifact_type, policy)

    def validate_retention_policies(self) -> None:
        """Validate all artifact retention policies before execution.

        Raises ``ValueError`` if any policy is invalid.
        """
        self.artifact_retention.validate_cleanup_schedule()


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
