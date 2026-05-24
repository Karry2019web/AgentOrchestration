"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class LifecycleState(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLING_BACK = "rolling_back"
    CANCELLED = "cancelled"


class ReducerTransition:
    """Represents a single reducer/dispatch transition with lifecycle metadata."""

    def __init__(
        self,
        entity_id: str,
        from_state: LifecycleState,
        to_state: LifecycleState,
        attempt: int = 1,
        revision: int = 1,
    ):
        self.entity_id = entity_id
        self.from_state = from_state
        self.to_state = to_state
        self.attempt = attempt
        self.revision = revision
        self.timestamp = time.time()


class TransitionError(Exception):
    """Raised when a reducer transition is rejected by the error store guard."""


class ReducerErrorStore:
    """Guards reducer/dispatch transitions with attempt, revision, and lifecycle checks.

    Rejects stale, duplicate, or policy-violating transitions before
    they commit scheduler, routing, queue, or workflow state.
    """

    def __init__(self):
        self._states: Dict[str, LifecycleState] = {}
        self._attempts: Dict[str, int] = {}
        self._revisions: Dict[str, int] = {}
        self._errors: List[Dict[str, Any]] = []

    def get_state(self, entity_id: str) -> LifecycleState:
        return self._states.get(entity_id, LifecycleState.PENDING)

    def get_attempt(self, entity_id: str) -> int:
        return self._attempts.get(entity_id, 0)

    def get_revision(self, entity_id: str) -> int:
        return self._revisions.get(entity_id, 0)

    def validate_transition(self, transition: ReducerTransition) -> bool:
        """Validate a transition against stored lifecycle state."""
        entity_id = transition.entity_id
        current_state = self.get_state(entity_id)
        current_attempt = self.get_attempt(entity_id)
        current_revision = self.get_revision(entity_id)

        if current_state == LifecycleState.COMPLETED and transition.to_state not in (
            LifecycleState.PENDING, LifecycleState.ROLLING_BACK,
        ):
            raise TransitionError(
                f"Cannot transition {entity_id} from {current_state.value} "
                f"to {transition.to_state.value}: entity is already completed"
            )

        if current_state == LifecycleState.FAILED and transition.to_state not in (
            LifecycleState.PENDING, LifecycleState.ROLLING_BACK,
        ):
            raise TransitionError(
                f"Cannot transition {entity_id} from {current_state.value} "
                f"to {transition.to_state.value}: entity is in failed state"
            )

        if current_state == LifecycleState.CANCELLED:
            raise TransitionError(
                f"Cannot transition {entity_id} from {current_state.value}: "
                f"entity was cancelled"
            )

        if current_state == LifecycleState.ROLLING_BACK and transition.to_state != LifecycleState.PENDING:
            raise TransitionError(
                f"Cannot transition {entity_id} from {current_state.value} "
                f"to {transition.to_state.value}: must complete rollback first"
            )

        if transition.attempt <= current_attempt:
            raise TransitionError(
                f"Stale attempt {transition.attempt} for {entity_id}: "
                f"current attempt is {current_attempt}"
            )

        if transition.revision < current_revision:
            raise TransitionError(
                f"Stale revision {transition.revision} for {entity_id}: "
                f"current revision is {current_revision}"
            )

        return True

    def commit_transition(self, transition: ReducerTransition) -> None:
        """Commit a validated transition to the error store."""
        entity_id = transition.entity_id
        self._states[entity_id] = transition.to_state
        self._attempts[entity_id] = transition.attempt
        if transition.revision > self._revisions.get(entity_id, 0):
            self._revisions[entity_id] = transition.revision
        logger.info(
            "Reducer transition committed: %s %s -> %s (attempt=%d, revision=%d)",
            entity_id, transition.from_state.value, transition.to_state.value,
            transition.attempt, transition.revision,
        )

    def record_error(self, entity_id: str, transition_info: str, error: str) -> None:
        """Record a rejected transition error for diagnostics."""
        self._errors.append({
            "entity_id": entity_id,
            "transition_info": transition_info,
            "error": error,
            "timestamp": time.time(),
        })
        logger.warning("Reducer error recorded: %s — %s (%s)", entity_id, error, transition_info)

    def get_errors(self, entity_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if entity_id:
            return [e for e in self._errors if e["entity_id"] == entity_id]
        return list(self._errors)

    def clear_errors(self, entity_id: Optional[str] = None) -> None:
        if entity_id:
            self._errors = [e for e in self._errors if e["entity_id"] != entity_id]
        else:
            self._errors.clear()


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [], "post_execute": [], "on_error": [], "on_complete": [],
        }
        self.reducer_store = ReducerErrorStore()

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        transition = ReducerTransition(
            entity_id=task_id,
            from_state=self.reducer_store.get_state(task_id),
            to_state=LifecycleState.RUNNING,
            attempt=self.reducer_store.get_attempt(task_id) + 1,
            revision=self.reducer_store.get_revision(task_id) + 1,
        )
        try:
            self.reducer_store.validate_transition(transition)
            self.reducer_store.commit_transition(transition)
        except TransitionError as e:
            self.reducer_store.record_error(task_id, "pre_execute", str(e))
            logger.error(f"Reducer rejected task {task_id} execution: {e}")
            return

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")
            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            result = await asyncio.wait_for(
                self._run_agent_task(agent, task), timeout=self.agent_timeout,
            )
            self.registry.update_status(agent_id, AgentStatus.PAUSED)
            for hook in self._hooks["post_execute"]:
                await hook(task, result)
            logger.info(f"Task {task_id} completed successfully")

            complete_transition = ReducerTransition(
                entity_id=task_id,
                from_state=LifecycleState.RUNNING,
                to_state=LifecycleState.COMPLETED,
                attempt=transition.attempt,
                revision=transition.revision,
            )
            self.reducer_store.commit_transition(complete_transition)
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            for hook in self._hooks["on_error"]:
                await hook(task, e)
            error_transition = ReducerTransition(
                entity_id=task_id,
                from_state=self.reducer_store.get_state(task_id),
                to_state=LifecycleState.FAILED,
                attempt=transition.attempt,
                revision=transition.revision,
            )
            self.reducer_store.commit_transition(error_transition)
            self.reducer_store.record_error(task_id, "execution", str(e))

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._execute_in_thread, agent, task)

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        return {"status": "completed", "output": f"Task {task['id']} processed by {agent['name']}"}
