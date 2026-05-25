"""Workflow Manager — Defines and executes multi-step agent workflows."""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from uuid import uuid4

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


@dataclass
class WorkflowNode:
    """A node in a workflow DAG with explicit dependency declarations.

    ``depends_on`` must list the **names** of nodes that must complete before
    this node runs.  An empty list means the node has no prerequisites and
    can be scheduled immediately (parallel with other root nodes).
    """

    name: str
    handler: Callable
    depends_on: List[str] = field(default_factory=list)
    retries: int = 0
    timeout: int = 300
    id: str = field(default_factory=lambda: str(uuid4()))
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: Optional[str] = None

    def __hash__(self) -> int:
        return hash(self.id)


class NodeDependencyError(ValueError):
    """Raised when a workflow node has an invalid or implicit dependency."""


class NodeDependencyValidator:
    """Validates that workflow node dependencies are explicitly declared.

    Prevents implicit dependency on declaration order by requiring every
    dependency to be declared via ``depends_on``.  Nodes added sequentially
    must declare their ordering or be treated as parallel-ready roots.
    """

    @staticmethod
    def validate_nodes(nodes: List[WorkflowNode]) -> List[str]:
        """Validate a list of nodes.  Return a list of error messages (empty = valid)."""
        errors: List[str] = []
        if not nodes:
            return errors

        name_map: Dict[str, WorkflowNode] = {}
        for n in nodes:
            if n.name in name_map:
                errors.append(f"Duplicate node name: '{n.name}'")
            name_map[n.name] = n

        # 1. Check that all declared dependencies exist
        for n in nodes:
            for dep_name in n.depends_on:
                if dep_name not in name_map:
                    errors.append(
                        f"Node '{n.name}' depends on unknown node '{dep_name}'"
                    )

        # 2. Detect implicit ordering: flag sequential nodes that may have
        #    an undeclared ordering dependency
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                if a.name in b.depends_on or b.name in a.depends_on:
                    continue
                a_name_lower = a.name.lower()
                b_name_lower = b.name.lower()
                handler_repr = repr(a.handler) + repr(b.handler)
                if a_name_lower in handler_repr.lower() and b_name_lower in handler_repr.lower():
                    errors.append(
                        f"Nodes '{a.name}' and '{b.name}' appear interdependent "
                        f"(handler references suggest coupling) but neither declares "
                        f"the dependency explicitly.  Add depends_on or refactor to "
                        f"remove the implicit ordering."
                    )

        # 3. Check for cycles
        adj: Dict[str, List[str]] = {n.name: list(n.depends_on) for n in nodes}
        for n in nodes:
            visited: Set[str] = set()
            path: List[str] = []

            def dfs(name: str) -> Optional[List[str]]:
                if name in visited:
                    return None
                visited.add(name)
                path.append(name)
                for dep in adj.get(name, []):
                    if dep in path:
                        cycle_start = path.index(dep)
                        return path[cycle_start:] + [dep]
                    cycle = dfs(dep)
                    if cycle:
                        return cycle
                path.pop()
                return None

            cycle = dfs(n.name)
            if cycle:
                errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")
                break

        return errors


class Workflow:
    def __init__(self, name: str, description: str = ""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps: List[WorkflowStep] = []
        self.nodes: List[WorkflowNode] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self._node_map: Dict[str, WorkflowNode] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def add_node(self, node: WorkflowNode) -> "Workflow":
        """Add a node with explicit dependencies to the workflow DAG."""
        self.nodes.append(node)
        self._node_map[node.name] = node
        return self

    def get_node(self, name: str) -> Optional[WorkflowNode]:
        """Look up a node by name."""
        return self._node_map.get(name)


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

        if workflow.nodes:
            return self._execute_dag(workflow)

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

    def _execute_dag(self, workflow: Workflow) -> bool:
        """Execute a DAG of nodes with explicit dependencies."""
        errors = NodeDependencyValidator.validate_nodes(workflow.nodes)
        if errors:
            logger.error("Node dependency validation failed: %s", errors)
            workflow.status = StepStatus.FAILED
            return False

        workflow.status = StepStatus.RUNNING

        node_map = {n.name: n for n in workflow.nodes}
        in_degree: Dict[str, int] = {n.name: len(n.depends_on) for n in workflow.nodes}
        dependents: Dict[str, List[WorkflowNode]] = defaultdict(list)
        for n in workflow.nodes:
            for dep in n.depends_on:
                dependents[dep].append(n)

        ready = {n for n in workflow.nodes if in_degree[n.name] == 0}

        while ready:
            batch = list(ready)
            ready.clear()
            for node in batch:
                node.status = StepStatus.RUNNING
                try:
                    result = node.handler()
                    node.result = result
                    node.status = StepStatus.COMPLETED
                except Exception as e:
                    node.error = str(e)
                    node.status = StepStatus.FAILED
                    workflow.status = StepStatus.FAILED
                    return False

                for dep_node in dependents.get(node.name, []):
                    in_degree[dep_node.name] -= 1
                    if in_degree[dep_node.name] == 0:
                        ready.add(dep_node)

        remaining = [n.name for n in workflow.nodes if n.status == StepStatus.PENDING]
        if remaining:
            logger.error("Unreachable nodes (possible cycle): %s", remaining)
            workflow.status = StepStatus.FAILED
            return False

        workflow.status = StepStatus.COMPLETED
        return True


__all__ = [
    "NodeDependencyError",
    "NodeDependencyValidator",
    "StepStatus",
    "Workflow",
    "WorkflowManager",
    "WorkflowNode",
    "WorkflowStep",
]
