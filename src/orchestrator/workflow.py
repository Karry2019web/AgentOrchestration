"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4
import time
import logging


class ArtifactRetentionCategory(Enum):
    """Categories of workflow artifacts with distinct retention rules."""
    LOG = "log"
    METRIC = "metric"
    CHECKPOINT = "checkpoint"
    RESULT = "result"
    TEMPORARY = "temporary"


ARTIFACT_RETENTION_POLICIES: Dict[ArtifactRetentionCategory, int] = {
    ArtifactRetentionCategory.LOG: 86400 * 7,         # 7 days
    ArtifactRetentionCategory.METRIC: 86400 * 30,      # 30 days
    ArtifactRetentionCategory.CHECKPOINT: 86400 * 90,  # 90 days
    ArtifactRetentionCategory.RESULT: 86400 * 365,     # 365 days
    ArtifactRetentionCategory.TEMPORARY: 3600,         # 1 hour
}


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CleanupSchedule:
    """Represents a scheduled cleanup entry for workflow artifacts."""

    def __init__(
        self,
        category: ArtifactRetentionCategory,
        created_at: float,
        retention_seconds: int,
    ):
        self.category = category
        self.created_at = created_at
        self.retention_seconds = retention_seconds

    @property
    def eligible_at(self) -> float:
        """Timestamp at which this artifact becomes eligible for cleanup."""
        return self.created_at + self.retention_seconds

    @property
    def is_overdue(self) -> bool:
        """Whether the artifact should already have been cleaned up."""
        return time.time() >= self.eligible_at

    def __repr__(self):
        return (
            f"CleanupSchedule(category={self.category.value}, "
            f"created_at={self.created_at:.0f}, "
            f"retention={self.retention_seconds}s, "
            f"eligible_at={self.eligible_at:.0f})"
        )


class ArtifactRetentionValidator:
    """Validates artifact retention policies before cleanup scheduling.

    Enforces retention invariants at workflow registration and pre-dispatch
    time so that invalid scheduling definitions cannot start executing.
    """

    def __init__(self):
        self._logger = logging.getLogger(__name__)
        self._violations: List[str] = []

    def validate_schedule(
        self,
        schedule: CleanupSchedule,
    ) -> bool:
        """Validate a single cleanup schedule entry.

        Returns True if valid, False if a policy violation is detected.
        Violations are recorded via logs and the internal violations list.
        """
        violations: List[str] = []

        # Rule 1: Retention must be positive
        if schedule.retention_seconds <= 0:
            violations.append(
                f"Non-positive retention ({schedule.retention_seconds}s) "
                f"for category {schedule.category.value}; "
                f"minimum is 1 second"
            )

        # Rule 2: Retention must not exceed the allowed maximum for the category
        max_allowed = ARTIFACT_RETENTION_POLICIES.get(schedule.category)
        if max_allowed is not None and schedule.retention_seconds > max_allowed:
            violations.append(
                f"Retention ({schedule.retention_seconds}s) exceeds "
                f"max allowed ({max_allowed}s) for category "
                f"{schedule.category.value}"
            )

        # Rule 3: Created-at must be a reasonable timestamp (past or near-present)
        now = time.time()
        if schedule.created_at > now + 300:
            violations.append(
                f"Created-at timestamp ({schedule.created_at:.0f}) "
                f"is in the future (now={now:.0f}); "
                f"cannot schedule cleanup for an artifact that does not exist yet"
            )

        # Rule 4: An overdue artifact must have at least 1s of retention remaining
        if schedule.is_overdue and schedule.retention_seconds < 3600:
            violations.append(
                f"Artifact is already overdue (eligible_at={schedule.eligible_at:.0f}) "
                f"with short retention ({schedule.retention_seconds}s); "
                f"cleanup should have already fired — rejecting stale schedule"
            )

        for v in violations:
            self._violations.append(v)
            self._logger.warning("Artifact retention violation: %s", v)

        self._logger.info(
            "Artifact retention validation: %s for %s schedule",
            "PASSED" if not violations else "FAILED",
            schedule.category.value,
        )
        return len(violations) == 0

    def validate_workflow(self, workflow_name: str, schedules: List[CleanupSchedule]) -> bool:
        """Validate all cleanup schedules for a workflow.

        Returns True if ALL schedules pass validation.
        """
        self._violations = []
        all_valid = True
        for s in schedules:
            if not self.validate_schedule(s):
                all_valid = False

        if not all_valid:
            self._logger.error(
                "Workflow '%s' has %d retention policy violation(s); "
                "registration rejected",
                workflow_name,
                len(self._violations),
            )
        return all_valid

    @property
    def violations(self) -> List[str]:
        return list(self._violations)


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
        self.cleanup_schedules: List[CleanupSchedule] = []

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def add_cleanup_schedule(self, schedule: CleanupSchedule) -> "Workflow":
        self.cleanup_schedules.append(schedule)
        return self


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}
        self._retention_validator = ArtifactRetentionValidator()

    @property
    def retention_validator(self) -> ArtifactRetentionValidator:
        return self._retention_validator

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def register_workflow(
        self,
        name: str,
        description: str = "",
        cleanup_schedules: Optional[List[CleanupSchedule]] = None,
    ) -> Optional[Workflow]:
        """Register a workflow with pre-dispatch artifact retention validation.

        Validates cleanup schedules before the workflow is stored. If validation
        fails, the workflow is rejected and None is returned — preventing bad
        scheduling graphs from ever starting execution.
        """
        schedules = cleanup_schedules or []
        if not self._retention_validator.validate_workflow(name, schedules):
            return None

        workflow = self.create_workflow(name, description)
        workflow.cleanup_schedules = schedules
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

# 2019-03-27T19:58:07 update

# 2019-05-09T09:42:56 update

# 2019-12-03T10:07:42 update

# 2020-01-16T18:43:28 update

# 2020-03-20T10:40:15 update

# 2020-04-17T15:36:50 update

# 2020-05-04T14:44:01 update

# 2020-06-16T13:17:31 update

# 2020-08-05T17:00:24 update

# 2020-09-04T08:29:23 update

# 2020-09-09T17:52:02 update

# 2020-10-23T10:57:44 update

# 2020-12-05T20:55:47 update

# 2021-01-05T09:57:38 update

# 2021-02-05T15:02:56 update

# 2021-04-20T18:28:08 update

# 2021-05-26T14:35:42 update

# 2021-06-14T19:08:08 update

# 2021-07-26T12:20:37 update

# 2021-08-12T19:14:49 update

# 2021-08-20T12:18:28 update

# 2021-11-04T15:19:39 update

# 2021-12-03T14:33:15 update

# 2022-01-06T08:17:48 update

# 2022-02-07T19:02:21 update

# 2022-04-21T14:14:44 update

# 2022-07-25T10:31:21 update

# 2022-10-14T08:10:01 update

# 2022-12-28T18:42:01 update

# 2023-02-14T18:15:32 update

# 2023-04-10T09:33:36 update

# 2023-05-19T20:21:33 update

# 2023-06-23T18:22:46 update

# 2023-08-04T08:48:21 update

# 2023-08-24T10:06:28 update

# 2023-11-02T12:04:00 update

# 2023-11-17T17:50:34 update

# 2024-02-05T20:02:21 update

# 2024-02-29T10:58:06 update

# 2024-03-19T17:12:37 update

# 2024-05-06T11:50:24 update

# 2024-05-10T09:50:49 update

# 2024-06-10T12:00:30 update

# 2024-06-25T09:40:26 update

# 2024-09-17T13:49:39 update

# 2024-10-14T17:39:35 update

# 2024-11-27T20:14:35 update

# 2024-12-25T19:31:41 update

# 2025-01-16T13:15:09 update

# 2025-02-05T14:06:59 update

# 2025-02-17T20:55:11 update

# 2025-04-30T19:36:53 update

# 2025-07-17T10:14:40 update

# 2025-08-29T12:13:15 update

# 2025-09-03T13:51:11 update

# 2025-09-19T16:08:24 update

# 2025-11-27T08:38:12 update

# 2026-01-27T13:23:38 update

# 2026-01-28T11:22:50 update
