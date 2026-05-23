"""Workflow Manager — Defines and executes multi-step agent workflows."""

from collections import defaultdict, deque
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set
from uuid import uuid4


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    FAILED_DEPENDENCY = "failed_dependency"
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
        self._dependencies: Dict[str, Set[str]] = {}

    def add_step(self, step: WorkflowStep, depends_on: Optional[List[str]] = None) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        if depends_on:
            resolved = set()
            for dep in depends_on:
                found = None
                for s in self.steps:
                    if s.name == dep or s.id == dep:
                        found = s
                        break
                if found:
                    resolved.add(found.id)
            if resolved:
                self._dependencies[step.id] = resolved
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def get_dependencies(self, step_id: str) -> Set[str]:
        return self._dependencies.get(step_id, set())

    def _topological_order(self) -> List[WorkflowStep]:
        in_degree: Dict[str, int] = {}
        graph: Dict[str, List[str]] = defaultdict(list)

        for step in self.steps:
            in_degree[step.id] = 0

        for step_id, deps in self._dependencies.items():
            for dep_id in deps:
                graph.setdefault(dep_id, [])
                graph[dep_id].append(step_id)
                in_degree[step_id] = in_degree.get(step_id, 0) + 1

        queue = deque()
        for step in self.steps:
            if in_degree.get(step.id, 0) == 0:
                queue.append(step)

        ordered = []
        while queue:
            step = queue.popleft()
            ordered.append(step)
            for next_id in graph.get(step.id, []):
                in_degree[next_id] -= 1
                if in_degree[next_id] == 0:
                    next_step = self._step_map.get(next_id)
                    if next_step:
                        queue.append(next_step)

        if len(ordered) != len(self.steps):
            cycle_steps = [s for s in self.steps if s not in ordered]
            for step in cycle_steps:
                step.error = f"Cycle detected: step '{step.name}' is part of a dependency cycle"
                step.status = StepStatus.FAILED
            ordered.extend(cycle_steps)

        return ordered

    def _check_fan_in_failure(self, step: WorkflowStep) -> bool:
        for dep_id in self._dependencies.get(step.id, set()):
            dep_step = self._step_map.get(dep_id)
            if dep_step and dep_step.status in (StepStatus.FAILED, StepStatus.FAILED_DEPENDENCY):
                step.status = StepStatus.FAILED_DEPENDENCY
                step.error = (
                    f"Dependency step '{dep_step.name}' failed with status "
                    f"'{dep_step.status.value}': {dep_step.error}"
                )
                return True
        return False


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

        ordered_steps = workflow._topological_order()
        for step in ordered_steps:
            if workflow._check_fan_in_failure(step):
                continue

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED

        statuses = {s.status for s in workflow.steps}
        if StepStatus.FAILED in statuses or StepStatus.FAILED_DEPENDENCY in statuses:
            workflow.status = StepStatus.FAILED
        else:
            workflow.status = StepStatus.COMPLETED
        return workflow.status == StepStatus.COMPLETED
