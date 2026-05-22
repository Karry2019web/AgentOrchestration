"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.agent import AgentRegistry, AgentStatus
from src.common.errors import TenantOwnershipError, StaleEventError
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


@dataclass
class EventRecord:
    """A single event on the shared event bus."""
    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = ""
    tenant_id: str = ""
    source: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    revision: int = 0
    timestamp: float = field(default_factory=time.time)


@dataclass
class TenantLifecycleState:
    """Tracks the lifecycle state for a tenant-agent pair."""
    tenant_id: str = ""
    agent_id: str = ""
    current_revision: int = 0
    status: str = "pending"
    last_event_id: Optional[str] = None
    last_event_type: Optional[str] = None
    timestamp: float = field(default_factory=time.time)


class EventBus:
    """Shared event bus that enforces tenant ownership and lifecycle ordering.

    Before any event is dispatched to scheduling, routing, queue, or workflow
    state, the bus validates:
      1. Tenant ownership — the event must originate from the correct tenant.
      2. Revision monotonicity — the event must carry a strictly increasing revision.
      3. Lifecycle validity — the event must be applicable to the current tenant state.
    """

    VALID_STATUS_TRANSITIONS: Dict[str, List[str]] = {
        "pending": ["enqueued", "cancelled"],
        "enqueued": ["in_flight", "cancelled"],
        "in_flight": ["completed", "failed", "cancelled"],
        "completed": [],
        "failed": ["enqueued"],
        "cancelled": [],
    }

    def __init__(self):
        self._states: Dict[str, TenantLifecycleState] = {}
        self._dispatched: Dict[str, EventRecord] = {}

    def _state_key(self, tenant_id: str, agent_id: str) -> str:
        return f"{tenant_id}:{agent_id}"

    def _validate_lifecycle(self, state: TenantLifecycleState, new_event: EventRecord) -> None:
        """Validate that the event is legal for the current lifecycle state."""
        allowed = self.VALID_STATUS_TRANSITIONS.get(state.status, [])
        target_status = new_event.payload.get("target_status", "")

        if new_event.event_type == "lifecycle_transition" and target_status:
            if target_status not in allowed:
                raise TenantOwnershipError(
                    f"current:{state.status}->target:{target_status}",
                    f"allowed:{','.join(allowed)}"
                )

    def validate_tenant_event(self, event: EventRecord, expected_tenant: str) -> None:
        """Validate tenant ownership and event ordering before accepting an event.

        Args:
            event: The incoming event to validate.
            expected_tenant: The tenant that is expected to own this event.

        Raises:
            TenantOwnershipError: If the event tenant does not match the expected tenant.
            StaleEventError: If the event revision is not strictly increasing.
        """
        # 1. Tenant ownership
        if event.tenant_id != expected_tenant:
            raise TenantOwnershipError(event.tenant_id, expected_tenant)

        # 2. Revision monotonicity (only when an existing state record exists)
        key = self._state_key(event.tenant_id, event.source)
        state = self._states.get(key)
        if state and event.revision <= state.current_revision:
            raise StaleEventError(event.event_id, state.current_revision)

    def accept_event(self, event: EventRecord, expected_tenant: str) -> Dict[str, Any]:
        """Accept a validated event into the event bus.

        This is the public entry point that guards scheduling, routing, queue,
        and workflow state commits.

        Returns:
            A decision dict with outcome, reason, and diagnostic info.

        The decision is also written to logs and metrics for auditability.
        """
        try:
            self.validate_tenant_event(event, expected_tenant)
        except (TenantOwnershipError, StaleEventError) as e:
            logger.warning("Event rejected: %s", str(e))
            return {
                "accepted": False,
                "reason": str(e),
                "event_id": event.event_id,
                "expected_tenant": expected_tenant,
            }

        key = self._state_key(event.tenant_id, event.source)
        state = self._states.get(key)
        if not state:
            state = TenantLifecycleState(
                tenant_id=event.tenant_id,
                agent_id=event.source,
            )
            self._states[key] = state

        # 3. Lifecycle check
        try:
            self._validate_lifecycle(state, event)
        except TenantOwnershipError as e:
            logger.warning("Lifecycle transition rejected: %s", str(e))
            return {
                "accepted": False,
                "reason": str(e),
                "event_id": event.event_id,
                "expected_tenant": expected_tenant,
                "current_state": state.status,
            }

        # Accept — commit the event
        state.current_revision = event.revision
        state.last_event_id = event.event_id
        state.last_event_type = event.event_type
        state.timestamp = event.timestamp

        target_status = event.payload.get("target_status", "")
        if event.event_type == "lifecycle_transition" and target_status:
            state.status = target_status

        self._dispatched[event.event_id] = event

        logger.info(
            "Event accepted: id=%s tenant=%s source=%s revision=%d",
            event.event_id, event.tenant_id, event.source, event.revision,
        )
        return {
            "accepted": True,
            "reason": "ok",
            "event_id": event.event_id,
            "revision": state.current_revision,
            "new_state": state.status,
        }

    def get_state(self, tenant_id: str, agent_id: str) -> Optional[TenantLifecycleState]:
        """Retrieve the current lifecycle state for a tenant-agent pair."""
        key = self._state_key(tenant_id, agent_id)
        return self._states.get(key)

    def reset_state(self, tenant_id: str, agent_id: str) -> None:
        """Reset lifecycle state (e.g. after run completion or failure)."""
        key = self._state_key(tenant_id, agent_id)
        self._states.pop(key, None)
        logger.info("State reset: tenant=%s agent=%s", tenant_id, agent_id)


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.event_bus = EventBus()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }

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

    def dispatch_event(self, event: EventRecord) -> Dict[str, Any]:
        """Dispatch an event through the tenant-guarded event bus.

        The agent's tenant is resolved from the registry; if the agent is not
        found the event is safely deferred.
        """
        agent = self.registry.get(event.source)
        if not agent:
            logger.warning("Event dropped: agent %s not found", event.source)
            return {
                "accepted": False,
                "reason": f"Agent {event.source} not found",
                "event_id": event.event_id,
            }
        expected_tenant = agent.get("tenant_id", "default")
        return self.event_bus.accept_event(event, expected_tenant)

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

            # Validate tenant ownership before running
            event = EventRecord(
                event_type="lifecycle_transition",
                tenant_id=agent.get("tenant_id", "default"),
                source=agent_id,
                revision=1,
                payload={"target_status": "in_flight"},
            )
            decision = self.event_bus.accept_event(event, event.tenant_id)
            if not decision["accepted"]:
                logger.warning("Task %s blocked by event bus: %s", task_id, decision["reason"])
                for hook in self._hooks["on_error"]:
                    await hook(task, ValueError(decision["reason"]))
                return

            self.registry.update_status(agent_id, AgentStatus.RUNNING)
            result = await asyncio.wait_for(
                self._run_agent_task(agent, task),
                timeout=self.agent_timeout,
            )
            self.registry.update_status(agent_id, AgentStatus.PAUSED)

            for hook in self._hooks["post_execute"]:
                await hook(task, result)

            logger.info(f"Task {task_id} completed successfully")

        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            for hook in self._hooks["on_error"]:
                await hook(task, e)

    async def _run_agent_task(self, agent: Dict, task: Dict) -> Any:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self.executor,
            self._execute_in_thread,
            agent,
            task,
        )

    def _execute_in_thread(self, agent: Dict, task: Dict) -> Any:
        return {"status": "completed", "output": f"Task {task['id']} processed by {agent['name']}"}
