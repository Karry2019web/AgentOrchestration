"""Workflow Manager — Defines and executes multi-step agent workflows."""

import re
import logging
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Template variable pattern: {{ variable_name }}
TEMPLATE_PATTERN = re.compile(r"\{\{\s*(\w+(?:\.\w+)*)\s*\}\}")


class TemplateResolver:
    """Resolves {{ variable }} templates against a context dictionary.

    Detects unresolved template variables during runtime parameter binding
    so invalid definitions cannot start executing.
    """

    def __init__(self, context: Dict[str, Any]):
        self._context = context

    def resolve(self, value: Any) -> Any:
        """Recursively resolve templates in a value (string, dict, or list)."""
        if isinstance(value, str):
            return self._resolve_string(value)
        elif isinstance(value, dict):
            return {k: self.resolve(v) for k, v in value.items()}
        elif isinstance(value, list):
            return [self.resolve(item) for item in value]
        return value

    def _resolve_string(self, template: str) -> str:
        def _replace_match(match: re.Match) -> str:
            var_path = match.group(1)
            resolved = self._resolve_path(var_path)
            if resolved is None:
                raise UnresolvedTemplateError(
                    f"Unresolved template variable: {{{{ {var_path} }}}}"
                )
            return str(resolved)

        try:
            return TEMPLATE_PATTERN.sub(_replace_match, template)
        except UnresolvedTemplateError:
            raise

    def _resolve_path(self, path: str) -> Any:
        parts = path.split(".")
        current = self._context
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part)
                if current is None:
                    return None
            else:
                return None
        return current

    def check_unresolved(self, value: Any) -> List[str]:
        """Find all unresolved template variables without raising.
        
        Returns list of unresolved variable names.
        """
        unresolved = []

        def _scan(v: Any) -> None:
            if isinstance(v, str):
                for match in TEMPLATE_PATTERN.finditer(v):
                    var_path = match.group(1)
                    if self._resolve_path(var_path) is None:
                        unresolved.append(var_path)
            elif isinstance(v, dict):
                for val in v.values():
                    _scan(val)
            elif isinstance(v, list):
                for item in v:
                    _scan(item)

        _scan(value)
        return unresolved


class UnresolvedTemplateError(ValueError):
    """Raised when a template variable cannot be resolved in the current context."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    def __init__(self, name: str, handler: Callable, retries: int = 0, 
                 timeout: int = 300, params: Optional[Dict] = None):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.params = params or {}
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


class Workflow:
    def __init__(self, name: str, description: str = "", 
                 context: Optional[Dict[str, Any]] = None):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.context = context or {}
        self.steps: List[WorkflowStep] = []
        self._step_map: Dict[str, WorkflowStep] = {}
        self.status = StepStatus.PENDING

    def add_step(self, step: WorkflowStep) -> "Workflow":
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id: str) -> Optional[WorkflowStep]:
        return self._step_map.get(step_id)

    def resolve_templates(self) -> List[str]:
        """Resolve all template variables against the workflow context.
        
        Returns a list of unresolved variable names, or raises UnresolvedTemplateError
        if any template cannot be resolved.
        
        Must be called before execution to catch invalid bindings early.
        """
        resolver = TemplateResolver(self.context)
        all_unresolved = []

        for step in self.steps:
            unresolved = resolver.check_unresolved(step.params)
            all_unresolved.extend(unresolved)

        # Deduplicate
        unique_unresolved = list(dict.fromkeys(all_unresolved))
        return unique_unresolved

    def validate_and_bind(self) -> None:
        """Validate all template variables are resolvable, then bind them.
        
        Raises UnresolvedTemplateError if any template variable is unresolved.
        This is the pre-dispatch validation gate — catches bad bindings before
        execution starts.
        """
        unresolved = self.resolve_templates()
        if unresolved:
            vars_str = ", ".join(unresolved)
            raise UnresolvedTemplateError(
                f"Workflow '{self.name}' has unresolved template variables: {vars_str}. "
                f"Missing context keys: {vars_str}"
            )

        # Bind templates into step params
        resolver = TemplateResolver(self.context)
        for step in self.steps:
            step.params = resolver.resolve(step.params)


class WorkflowManager:
    def __init__(self):
        self._workflows: Dict[str, Workflow] = {}

    def create_workflow(self, name: str, description: str = "",
                        context: Optional[Dict[str, Any]] = None) -> Workflow:
        workflow = Workflow(name, description, context=context)
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

        # Validate template variables before execution
        try:
            workflow.validate_and_bind()
        except UnresolvedTemplateError as e:
            logger.error(f"Workflow '{workflow.name}' rejected: {e.message}")
            workflow.status = StepStatus.FAILED
            return False

        workflow.status = StepStatus.RUNNING
        for step in workflow.steps:
            step.status = StepStatus.RUNNING
            try:
                result = step.handler(**step.params) if step.params else step.handler()
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

# 2021-01-15T19:23:40 update

# 2021-02-03T20:43:12 update

# 2021-03-16T12:26:47 update

# 2021-04-20T14:33:28 update

# 2021-10-14T15:03:32 update

# 2021-10-21T17:24:55 update

# 2021-11-16T17:01:08 update

# 2021-11-22T09:51:21 update

# 2021-12-21T16:15:47 update

# 2022-03-23T16:52:27 update

# 2022-12-21T09:25:50 update

# 2023-01-09T09:55:25 update

# 2023-01-13T11:06:15 update

# 2023-01-26T11:00:59 update

# 2023-02-23T08:56:54 update

# 2023-05-17T08:07:16 update

# 2023-06-06T17:09:34 update

# 2023-06-13T10:35:28 update

# 2023-08-24T20:36:06 update

# 2023-10-30T19:10:13 update

# 2024-01-02T08:27:25 update

# 2024-01-24T12:13:15 update

# 2024-02-08T13:35:49 update

# 2024-05-07T16:09:24 update

# 2024-05-11T09:48:46 update

# 2024-05-21T19:25:41 update

# 2024-06-05T12:00:30 update

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

