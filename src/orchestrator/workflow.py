"""Workflow Manager — Defines and executes multi-step agent workflows."""

from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4
import logging

logger = logging.getLogger(__name__)


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
        self.depends_on: Set[str] = set()  # step IDs this step depends on


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

    def add_step_with_dependencies(self, step: WorkflowStep, depends_on: List[WorkflowStep]) -> "Workflow":
        """Add a step that depends on one or more predecessor steps (fan-in join)."""
        for dep in depends_on:
            step.depends_on.add(dep.id)
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def validate_dependencies(self) -> List[str]:
        """Validate the dependency graph and return any errors found.

        Checks for:
        - Missing dependencies (referenced step IDs that don't exist)
        - Circular dependencies
        """
        errors: List[str] = []

        for step in self.steps:
            for dep_id in step.depends_on:
                if dep_id not in self._step_map:
                    errors.append(
                        f"Step '{step.name}' depends on unknown step id '{dep_id}'"
                    )

        # Check for cycles using DFS
        visited: Set[str] = set()  # permanently visited
        rec_stack: Set[str] = set()  # currently on the recursion stack

        def _has_cycle(step_id: str) -> bool:
            if step_id in rec_stack:
                return True
            if step_id in visited:
                return False
            rec_stack.add(step_id)
            step = self._step_map.get(step_id)
            if step:
                for dep_id in step.depends_on:
                    if _has_cycle(dep_id):
                        return True
            rec_stack.discard(step_id)
            visited.add(step_id)
            return False

        for step in self.steps:
            if step.id not in visited:
                if _has_cycle(step.id):
                    errors.append(
                        f"Circular dependency detected involving step '{step.name}'"
                    )

        return errors


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "") -> Workflow:
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def register_workflow(self, workflow: Workflow) -> bool:
        """Register a workflow, validating its dependency graph first.

        Returns True if the workflow passes validation and is registered.
        Returns False if validation fails — the workflow is rejected.
        """
        errors = workflow.validate_dependencies()
        if errors:
            logger.error(
                "Workflow '%s' rejected during registration: %s",
                workflow.name,
                "; ".join(errors),
            )
            return False
        self._workflows[workflow.id] = workflow
        logger.info("Workflow '%s' registered successfully (id=%s)", workflow.name, workflow.id)
        return True

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

        # Resolve fan-in order: run steps in topological order
        executed: Set[str] = set()
        failed_steps: Dict[str, str] = {}  # step_id -> error message
        skipped_steps: Set[str] = set()

        def _deps_satisfied(step: WorkflowStep) -> bool:
            for dep_id in step.depends_on:
                if dep_id not in executed:
                    return False
            return True

        def _any_dep_failed(step: WorkflowStep) -> bool:
            for dep_id in step.depends_on:
                if dep_id in failed_steps:
                    return True
            return False

        # Execute steps in dependency order
        remaining = set(step.id for step in workflow.steps)

        while remaining:
            progress = False
            for step in workflow.steps:
                if step.id not in remaining:
                    continue
                if not _deps_satisfied(step):
                    continue

                # If any dependency failed, skip this step — preserve failure status
                if _any_dep_failed(step):
                    step.status = StepStatus.SKIPPED
                    skipped_steps.add(step.id)
                    remaining.discard(step.id)
                    logger.info(
                        "Step '%s' skipped — dependency '%s' failed (workflow %s)",
                        step.name,
                        next((s.name for s in workflow.steps if s.id in step.depends_on and s.id in failed_steps), "unknown"),
                        workflow.name,
                    )
                    progress = True
                    continue

                # Execute the step
                step.status = StepStatus.RUNNING
                try:
                    result = step.handler()
                    step.result = result
                    step.status = StepStatus.COMPLETED
                    executed.add(step.id)
                    remaining.discard(step.id)
                    progress = True
                except Exception as e:
                    step.error = str(e)
                    step.status = StepStatus.FAILED
                    failed_steps[step.id] = str(e)
                    remaining.discard(step.id)
                    progress = True
                    logger.warning(
                        "Step '%s' failed in workflow '%s': %s",
                        step.name,
                        workflow.name,
                        e,
                    )

            if not progress:
                # Deadlock: remaining steps have unmet dependencies that will never resolve
                for step in workflow.steps:
                    if step.id in remaining:
                        step.status = StepStatus.SKIPPED
                        skipped_steps.add(step.id)
                        remaining.discard(step.id)
                        logger.warning(
                            "Step '%s' in workflow '%s' skipped due to unresolvable dependency",
                            step.name,
                            workflow.name,
                        )
                break

        if failed_steps:
            workflow.status = StepStatus.FAILED
            logger.warning(
                "Workflow '%s' failed after %d completed, %d failed, %d skipped",
                workflow.name,
                len(executed),
                len(failed_steps),
                len(skipped_steps),
            )
            return False

        workflow.status = StepStatus.COMPLETED
        logger.info(
            "Workflow '%s' completed successfully (%d steps)",
            workflow.name,
            len(executed),
        )
        return True
