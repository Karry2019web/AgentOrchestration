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
    ROLLED_BACK = "rolled_back"
    BLOCKED = "blocked"


class WorkflowStep:
    def __init__(self, name, handler, retries=0, timeout=300):
        self.id = str(uuid4())
        self.name = name
        self.handler = handler
        self.retries = retries
        self.timeout = timeout
        self.status = StepStatus.PENDING
        self.result = None
        self.error = None


class CompensationAction:
    def __init__(self, step_id, step_name, undo_handler):
        self.step_id = step_id
        self.step_name = step_name
        self.undo_handler = undo_handler
        self.executed = False
        self.error = None


class CompensationEngine:
    def __init__(self):
        self._compensated = False
        self._compensated_at = None
        self._compensation_actions = []
        self._downstream_blocked = False
        self._blocked_step_ids = set()

    @property
    def is_compensated(self):
        return self._compensated

    @property
    def downstream_blocked(self):
        return self._downstream_blocked

    def register_compensation(self, action):
        self._compensation_actions.append(action)

    def trigger_compensation(self, failed_step_name):
        import time
        self._compensated = True
        self._compensated_at = time.time()
        self._downstream_blocked = True
        self._blocked_step_ids.clear()
        for action in self._compensation_actions:
            try:
                action.undo_handler()
                action.executed = True
            except Exception as e:
                action.error = str(e)

    def block_downstream(self, step_id):
        if self._downstream_blocked:
            self._blocked_step_ids.add(step_id)

    def is_step_blocked(self, step_id):
        return step_id in self._blocked_step_ids or self._downstream_blocked

    def reset(self):
        self._compensated = False
        self._compensated_at = None
        self._compensation_actions.clear()
        self._downstream_blocked = False
        self._blocked_step_ids.clear()


class Workflow:
    def __init__(self, name, description=""):
        self.id = str(uuid4())
        self.name = name
        self.description = description
        self.steps = []
        self._step_map = {}
        self.status = StepStatus.PENDING
        self.compensation = CompensationEngine()

    def add_step(self, step):
        self.steps.append(step)
        self._step_map[step.id] = step
        return self

    def get_step(self, step_id):
        return self._step_map.get(step_id)


class WorkflowManager:
    def __init__(self):
        self._workflows = {}

    def create_workflow(self, name, description=""):
        workflow = Workflow(name, description)
        self._workflows[workflow.id] = workflow
        return workflow

    def get_workflow(self, workflow_id):
        return self._workflows.get(workflow_id)

    def list_workflows(self):
        return list(self._workflows.values())

    def delete_workflow(self, workflow_id):
        return self._workflows.pop(workflow_id, None) is not None

    def execute_workflow(self, workflow_id):
        workflow = self._workflows.get(workflow_id)
        if not workflow:
            return False

        workflow.status = StepStatus.RUNNING
        completed_before_failure = []

        for idx, step in enumerate(workflow.steps):
            if workflow.compensation.is_step_blocked(step.id):
                step.status = StepStatus.BLOCKED
                continue

            step.status = StepStatus.RUNNING
            try:
                result = step.handler()
                step.result = result
                step.status = StepStatus.COMPLETED
                completed_before_failure.append(step)
            except Exception as e:
                step.error = str(e)
                step.status = StepStatus.FAILED
                workflow.status = StepStatus.FAILED

                for completed_step in completed_before_failure:
                    def make_undo(s):
                        return lambda: setattr(s, 'status', StepStatus.ROLLED_BACK)
                    action = CompensationAction(
                        step_id=completed_step.id,
                        step_name=completed_step.name,
                        undo_handler=make_undo(completed_step),
                    )
                    workflow.compensation.register_compensation(action)

                workflow.compensation.trigger_compensation(step.name)

                for remaining_step in workflow.steps[idx + 1:]:
                    workflow.compensation.block_downstream(remaining_step.id)
                    remaining_step.status = StepStatus.BLOCKED

                return False

        workflow.status = StepStatus.COMPLETED
        return True
