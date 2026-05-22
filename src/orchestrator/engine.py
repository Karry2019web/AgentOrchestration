"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

# Known event types recognized by this orchestrator version
KNOWN_EVENT_TYPES = frozenset({
    "task.submit",
    "task.start",
    "task.complete",
    "task.fail",
    "task.cancel",
    "task.progress",
    "agent.register",
    "agent.deregister",
    "agent.status_change",
    "workflow.start",
    "workflow.complete",
    "workflow.fail",
    "system.health",
    "system.config_change",
})


class EventDispatcher:
    """Validates and dispatches events, quarantining unknown event types."""

    def __init__(self):
        self._known_types = KNOWN_EVENT_TYPES
        self._quarantined_events: list = []
        self._revision_counter: Dict[str, int] = {}

    def is_known_event_type(self, event_type: str) -> bool:
        """Check if an event type is recognized."""
        return event_type in self._known_types

    def validate_event(self, event: Dict) -> Dict:
        """Validate an event before dispatch. Returns decision."""
        event_type = event.get("type", "")
        tenant_id = event.get("tenant_id", "default")
        revision = event.get("revision", 0)
        event_id = event.get("id", "")

        if not event_type:
            return {
                "accepted": False,
                "reason": "missing_event_type",
                "quarantine": True,
            }

        if not self.is_known_event_type(event_type):
            self._quarantined_events.append({
                "event_id": event_id,
                "event_type": event_type,
                "tenant_id": tenant_id,
                "revision": revision,
                "reason": "unknown_event_type",
            })
            return {
                "accepted": False,
                "reason": "unknown_event_type",
                "quarantine": True,
                "event_type": event_type,
            }

        # Validate revision monotonicity per tenant
        tenant_rev = self._revision_counter.get(tenant_id, -1)
        if revision <= tenant_rev:
            self._quarantined_events.append({
                "event_id": event_id,
                "event_type": event_type,
                "tenant_id": tenant_id,
                "revision": revision,
                "reason": "stale_revision",
            })
            return {
                "accepted": False,
                "reason": "stale_revision",
                "quarantine": True,
            }

        self._revision_counter[tenant_id] = revision
        return {"accepted": True, "reason": "ok"}

    def get_quarantined_events(self) -> list:
        """Return list of quarantined events."""
        return list(self._quarantined_events)

    def clear_quarantine(self) -> int:
        """Clear quarantine and return count."""
        count = len(self._quarantined_events)
        self._quarantined_events.clear()
        return count

    def add_known_type(self, event_type: str) -> None:
        """Register a new event type (used during rolling upgrades)."""
        # Convert to mutable set, add, then recreate
        mutable = set(self._known_types)
        mutable.add(event_type)
        self._known_types = frozenset(mutable)

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self.event_dispatcher = EventDispatcher()
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

    def dispatch_event(self, event: Dict[str, Any]) -> Dict:
        """Dispatch an external event through the orchestrator, with validation."""
        decision = self.event_dispatcher.validate_event(event)
        if decision.get("accepted"):
            logger.info(f"Event {event.get('id')} accepted: {event.get('type')}")
            asyncio.create_task(self._handle_dispatch_event(event))
        else:
            logger.warning(
                f"Event {event.get('id')} rejected: {decision.get('reason')}"
            )
        return decision

    async def _handle_dispatch_event(self, event: Dict) -> None:
        """Process an accepted external event."""
        event_type = event.get("type", "")
        event_id = event.get("id", "")

        if event_type == "task.submit" and "task" in event:
            await self._execute_task(event["task"])
        elif event_type == "agent.status_change" and "agent_id" in event:
            agent_id = event["agent_id"]
            status = event.get("status", "running")
            self.registry.update_status(agent_id, AgentStatus(status))

        for hook in self._hooks.get("post_execute", []):
            try:
                if asyncio.iscoroutinefunction(hook):
                    await hook(event)
                else:
                    hook(event)
            except Exception as e:
                logger.error(f"Dispatch hook failed for {event_id}: {e}")

    def get_quarantined_events(self) -> list:
        """Return quarantined events from the event dispatcher."""
        return self.event_dispatcher.get_quarantined_events()

    def clear_quarantine(self) -> int:
        """Clear quarantined events."""
        return self.event_dispatcher.clear_quarantine()

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        event_type = task.get("event_type", "task.submit")

        # Validate event type before processing
        decision = self.event_dispatcher.validate_event({
            "id": task_id,
            "type": event_type,
            "tenant_id": task.get("tenant_id", "default"),
            "revision": task.get("revision", 0),
        })
        if not decision.get("accepted"):
            reason = decision.get("reason", "validation_failed")
            logger.warning(f"Task {task_id} rejected: {reason}")
            # Notify error hooks
            for hook in self._hooks["on_error"]:
                await hook(task, ValueError(f"Event rejected: {reason}"))
            return]
        agent_id = task["target_agent"]
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        for hook in self._hooks["pre_execute"]:
            await hook(task)

        try:
            agent = self.registry.get(agent_id)
            if not agent:
                raise ValueError(f"Agent {agent_id} not found")

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

# 2019-04-24T14:55:39 update

# 2019-05-01T16:01:52 update

# 2019-05-27T19:55:55 update

# 2019-06-02T09:38:08 update

# 2019-07-10T15:36:32 update

# 2019-07-22T11:36:40 update

# 2019-08-28T10:50:39 update

# 2019-08-30T14:21:57 update

# 2019-09-12T18:46:28 update

# 2019-10-02T09:55:59 update

# 2019-10-03T16:01:13 update

# 2019-12-03T13:07:37 update

# 2020-01-10T13:47:02 update

# 2020-01-31T13:14:49 update

# 2020-03-11T08:03:44 update

# 2020-03-31T15:51:14 update

# 2020-04-10T11:21:15 update

# 2020-06-08T09:31:33 update

# 2020-06-16T20:32:00 update

# 2020-07-21T18:48:01 update

# 2020-09-29T15:16:08 update

# 2020-11-18T14:09:09 update

# 2020-11-26T18:02:40 update

# 2021-01-07T11:18:24 update

# 2021-04-05T15:49:29 update

# 2021-04-27T11:58:27 update

# 2021-05-17T14:54:17 update

# 2021-06-07T11:46:07 update

# 2021-08-31T14:55:54 update

# 2021-09-10T17:29:34 update

# 2021-09-14T10:27:30 update

# 2021-10-06T14:04:05 update

# 2022-03-15T18:11:19 update

# 2022-09-15T18:32:09 update

# 2022-11-17T08:15:16 update

# 2023-02-17T12:24:53 update

# 2023-04-25T14:26:37 update

# 2023-05-22T09:03:39 update

# 2023-09-06T20:26:58 update

# 2023-11-28T17:54:23 update

# 2023-12-27T15:38:11 update

# 2024-03-12T20:10:32 update

# 2024-04-04T20:43:06 update

# 2024-05-27T12:23:51 update

# 2024-05-27T16:42:42 update

# 2024-07-23T13:27:05 update

# 2024-07-24T19:24:13 update

# 2024-11-03T18:25:58 update

# 2025-04-23T20:03:19 update

# 2026-02-16T17:12:09 update

# 2026-03-12T11:33:28 update
