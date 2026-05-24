"""Workflow Manager — Defines and executes multi-step agent workflows."""

import re
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Union
from uuid import uuid4


_TIME_UNITS = {
    "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
    "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
    "h": "hours", "hr": "hours", "hrs": "hours", "hour": "hours", "hours": "hours",
    "d": "days", "day": "days", "days": "days",
}

_SECONDS_PER_UNIT = {
    "seconds": 1,
    "minutes": 60,
    "hours": 3600,
    "days": 86400,
}

_UNIT_PATTERN = "|".join(re.escape(u) for u in _TIME_UNITS)
_DURATION_RE = re.compile(r"^(\d+(\.\d+)?)\s*(" + _UNIT_PATTERN + r")$", re.IGNORECASE)


class DurationParseError(ValueError):
    """Raised when a duration string cannot be parsed or contains conflicting units."""


def parse_duration(value: Union[str, int, float]) -> int:
    """Parse a duration string or numeric value into total seconds."""
    if isinstance(value, (int, float)):
        if value < 0:
            raise DurationParseError(f"Negative duration {value} is not allowed")
        return int(value)

    if not isinstance(value, str):
        raise DurationParseError(f"Unsupported duration type: {type(value).__name__}")

    value = value.strip()
    if not value:
        raise DurationParseError("Duration string must not be empty")

    if value.isdigit() or (value.startswith("-") and value[1:].isdigit()):
        secs = int(value)
        if secs < 0:
            raise DurationParseError(f"Negative duration {secs} is not allowed")
        return secs

    m = _DURATION_RE.match(value)
    if not m:
        raise DurationParseError(
            f"Unrecognized duration format: '{value}'. "
            "Use a number with unit suffix (e.g. '300', '5m', '2h', '1d')."
        )

    amount = float(m.group(1))
    unit_raw = m.group(3).lower()
    unit_category = _TIME_UNITS[unit_raw]
    multiplier = _SECONDS_PER_UNIT[unit_category]

    if amount < 0:
        raise DurationParseError(f"Negative duration {value} is not allowed")

    return int(amount * multiplier)


def validate_timeout_unit_consistency(*timeouts: Union[str, int, float]) -> None:
    """Check that all timeout values use a consistent unit family."""
    seen_categories: set[str] = set()
    for t in timeouts:
        if isinstance(t, str):
            t_stripped = t.strip()
            m = _DURATION_RE.match(t_stripped)
            if m:
                unit_raw = m.group(3).lower()
                seen_categories.add(_TIME_UNITS[unit_raw])

    if len(seen_categories) > 1:
        raise DurationParseError(
            f"Conflicting timeout units detected: {seen_categories}. "
            "All timeouts for a single step must use the same unit."
        )


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStep:
    def __init__(
        self,
        name: str,
        handler: Callable,
        retries: int = 0,
        timeout: Union[str, int, float] = 300,
    ):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = parse_duration(timeout)
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