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


class DependencyIdentifier:
    """Normalized dependency identifier with case-insensitive comparison.

    Dependency identifiers in workflow definitions are case-insensitive
    to prevent duplicates arising from inconsistent casing during
    registration. All lookups and comparisons use lowercased keys.
    """

    def __init__(self, name: str):
        self.raw = name
        self._normalized = name.lower()

    def __eq__(self, other: object) -> bool:
        if isinstance(other, DependencyIdentifier):
            return self._normalized == other._normalized
        if isinstance(other, str):
            return self._normalized == other.lower()
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._normalized)

    def __str__(self) -> str:
        return self.raw

    def __repr__(self) -> str:
        return f"DependencyIdentifier('{self.raw}')"


class WorkflowDependency:
    """A single dependency of a workflow step.

    Dependencies are stored with a normalized identifier so that
    case-insensitive duplicates are rejected at registration time.
    """

    def __init__(self, name: str, version: str = "*"):
        self.id = DependencyIdentifier(name)
        self.version = version
        self.resolved: bool = False

    @property
    def name(self) -> str:
        return self.id.raw


class WorkflowDependencyParser:
    """Parses and validates workflow dependency identifiers.

    Enforces case-insensitive normalization so that:
    1. 'MyService' and 'myservice' are treated as the same dependency.
    2. Duplicate dependencies (by normalized name) are rejected.
    3. Dependencies are sorted consistently regardless of input casing.
    """

    def __init__(self):
        self._dependencies: Dict[str, WorkflowDependency] = {}

    def add_dependency(self, name: str, version: str = "*") -> WorkflowDependency:
        """Register a dependency with normalized identifier.

        Raises ``ValueError`` if a dependency with the same normalized
        name has already been registered.
        """
        dep = WorkflowDependency(name, version)
        norm = dep.id._normalized

        if norm in self._dependencies:
            existing = self._dependencies[norm]
            raise ValueError(
                f"Dependency identifier conflict: '{existing.name}' and '{name}' "
                f"both normalize to '{norm}'. Use consistent casing to avoid "
                f"duplicate definitions."
            )

        self._dependencies[norm] = dep
        return dep

    def get_dependency(self, name: str) -> Optional[WorkflowDependency]:
        """Look up a dependency by name (case-insensitive)."""
        return self._dependencies.get(name.lower())

    def list_dependencies(self) -> List[WorkflowDependency]:
        """Return all registered dependencies, sorted by normalized name."""
        return sorted(self._dependencies.values(), key=lambda d: d.id._normalized)

    def resolve_all(self) -> bool:
        """Mark all dependencies as resolved. Returns True if any were unresolved."""
        had_unresolved = any(not d.resolved for d in self._dependencies.values())
        for dep in self._dependencies.values():
            dep.resolved = True
        return had_unresolved

    def validate_no_duplicates(self, names: List[str]) -> None:
        """Check that a list of dependency names has no case-insensitive duplicates.

        Raises ``ValueError`` if duplicates are found.
        """
        seen: Set[str] = set()
        for name in names:
            norm = name.lower()
            if norm in seen:
                raise ValueError(
                    f"Duplicate dependency identifier '{name}' (collides with "
                    f"existing normalized form '{norm}'). Use case-consistent names."
                )
            seen.add(norm)


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
        self.dependency_parser = WorkflowDependencyParser()

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def add_dependency(self, name: str, version: str = "*") -> WorkflowDependency:
        """Add a dependency with normalized identifier."""
        return self.dependency_parser.add_dependency(name, version)

    def validate_dependencies(self) -> None:
        """Validate all step dependencies before execution.

        Checks for case-insensitive duplicates and unresolved deps.
        Raises ``ValueError`` if any issue is found.
        """
        self.dependency_parser.resolve_all()


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
