"""Workflow Manager — Defines and executes multi-step agent workflows with sandboxed condition evaluation."""

import ast
import logging
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


class ConditionViolationError(Exception):
    """Raised when a workflow condition cannot be safely evaluated in the sandbox."""
    pass


class SandboxExpressionError(Exception):
    """Raised when a sandbox expression evaluation fails."""
    pass


# ---- Safe expression evaluator ----

_ALLOWED_BUILTINS: Set[str] = {
    "True", "False", "None",
    "abs", "all", "any", "bool", "dict", "float", "int", "len",
    "list", "max", "min", "set", "sorted", "str", "sum", "tuple", "type",
    "isinstance", "issubclass", "hasattr", "getattr",
    "enumerate", "filter", "map", "range", "reversed", "zip",
    "pow", "round", "divmod",
}

_FORBIDDEN_NODE_TYPES = (
    ast.Import, ast.ImportFrom,
    ast.Call,
    ast.Subscript,
    ast.Attribute,
    ast.Assign, ast.AugAssign, ast.AnnAssign, ast.Delete,
    ast.For, ast.While, ast.Try, ast.With, ast.Raise,
    ast.Global, ast.Nonlocal,
    ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
    ast.Yield, ast.YieldFrom, ast.Await,
    ast.Starred,
)

_FORBIDDEN_ATTRS: Set[str] = {
    "__import__", "__builtins__", "__class__", "__bases__", "__subclasses__",
    "__globals__", "__code__", "__closure__", "__dict__", "__getattribute__",
    "__del__", "__setattr__", "__call__", "__reduce__", "__reduce_ex__",
    "__init__", "__new__", "__prepare__",
    "eval", "exec", "compile", "open", "execfile", "input",
    "getattr", "setattr", "delattr",
    "import", "__import__",
}


def _check_sandbox_expression(expression: str, context_keys: Set[str]) -> None:
    """Validate that an expression is safe to evaluate."""
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise ConditionViolationError(f"Invalid expression syntax: {e}")

    for node in ast.walk(tree):
        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            raise ConditionViolationError(
                f"Forbidden construct in sandbox expression: {type(node).__name__}"
            )
        if isinstance(node, ast.Attribute):
            if isinstance(node.attr, str) and node.attr.startswith("__"):
                raise ConditionViolationError(
                    f"Forbidden attribute access on dunder name: '{node.attr}'"
                )
            if node.attr in _FORBIDDEN_ATTRS:
                raise ConditionViolationError(
                    f"Forbidden attribute access: '{node.attr}'"
                )
        if isinstance(node, ast.Name):
            if node.id in _FORBIDDEN_ATTRS:
                raise ConditionViolationError(
                    f"Forbidden name in sandbox expression: '{node.id}'"
                )
            if node.id not in _ALLOWED_BUILTINS and node.id not in context_keys:
                raise ConditionViolationError(
                    f"Unknown variable '{node.id}' not in allowed context keys: {sorted(context_keys)}"
                )
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id not in _ALLOWED_BUILTINS:
                raise ConditionViolationError(
                    f"Forbidden function call in sandbox expression: '{func.id}'"
                )


def _evaluate_sandbox_safe(expression: str, context: Dict[str, Any]) -> bool:
    """Evaluate a whitelisted expression against a sandboxed context dict."""
    context_keys = set(context.keys())
    _check_sandbox_expression(expression, context_keys)

    safe_builtins = {name: __builtins__[name] for name in _ALLOWED_BUILTINS
                     if name in __builtins__}
    safe_globals = {"__builtins__": safe_builtins}

    try:
        result = eval(expression, safe_globals, context)
        if not isinstance(result, bool):
            raise SandboxExpressionError(
                f"Condition expression must evaluate to bool, got {type(result).__name__}: {result}"
            )
        return result
    except ConditionViolationError:
        raise
    except Exception as e:
        raise SandboxExpressionError(f"Sandbox expression evaluation failed: {e}")


# ---- Workflow Condition ----

class WorkflowCondition:
    """A condition evaluated in a sandboxed context before a workflow step executes."""

    def __init__(self, expression: str, description: str = ""):
        if not expression or not expression.strip():
            raise ConditionViolationError("Condition expression cannot be empty")
        _check_sandbox_expression(expression, set())
        self.expression = expression.strip()
        self.description = description

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate this condition in a sandbox with the given context."""
        result = _evaluate_sandbox_safe(self.expression, context)
        return result

    def __repr__(self) -> str:
        return f"WorkflowCondition('{self.expression}')"


# ---- WorkflowStep with condition support ----

class WorkflowStep:
    def __init__(self, name: str, handler: Callable,
                 condition: Optional[WorkflowCondition] = None,
                 retries: int = 0, timeout: int = 300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.condition = condition
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result: Any = None
        self.error: Optional[str] = None


# ---- Workflow ----

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


# ---- WorkflowManager with condition validation ----

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

    def validate_workflow(self, workflow_id: str) -> List[str]:
        """Validate all conditions in a workflow at registration/pre-dispatch time."""
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return ["Workflow not found"]

        errors: List[str] = []
        for i, step in enumerate(workflow.steps):
            if step.condition is not None:
                try:
                    _check_sandbox_expression(step.condition.expression, set())
                except ConditionViolationError as e:
                    errors.append(f"Step {i} ('{step.name}'): {e}")
        return errors

    def execute_workflow(self, workflow_id: str,
                         condition_context: Optional[Dict[str, Any]] = None) -> bool:
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        # Pre-dispatch validation: reject workflows with bad conditions
        validation_errors = self.validate_workflow(workflow_id)
        if validation_errors:
            logger.error(
                "Workflow %s rejected at pre-dispatch: %s",
                workflow_id, "; ".join(validation_errors)
            )
            workflow.status = StepStatus.FAILED
            return False

        context = dict(condition_context or {})
        workflow.status = StepStatus.RUNNING

        for step in workflow.steps:
            if step.condition is not None:
                try:
                    should_run = step.condition.evaluate(context)
                except (ConditionViolationError, SandboxExpressionError) as e:
                    logger.warning(
                        "Condition evaluation failed for step '%s': %s - skipping step",
                        step.name, e
                    )
                    step.status = StepStatus.SKIPPED
                    step.error = str(e)
                    continue

                if not should_run:
                    logger.info(
                        "Condition '%s' evaluated to False for step '%s' - skipping",
                        step.condition.expression, step.name
                    )
                    step.status = StepStatus.SKIPPED
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
