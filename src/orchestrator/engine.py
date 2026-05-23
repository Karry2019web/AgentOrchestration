"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.events import (
    EventQuarantine,
    EventType,
    LifecycleRevision,
)
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    """Orchestration engine with event quarantine during version upgrades."""

    def __init__(
        self,
        max_workers: int = 10,
        agent_timeout: int = 300,
        version: str = "1.0.0",
    ):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }
        # Event quarantine for rolling version upgrades
        self.quarantine = EventQuarantine()
        self._current_revision = LifecycleRevision(
            version=version,
        )
        self._revision_sequence: int = 0

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                # Phase 1: quarantine check before dispatch
                event_type = task.get("type", "unknown")
                task_revision = LifecycleRevision.from_dict(
                    task.get("_revision", {})
                )
                if not self.quarantine.accepts(
                    event_type, task_revision, self._current_revision
                ):
                    self.quarantine.quarantine(
                        task,
                        reason=(
                            f"Unknown or version-mismatched event type "
                            f"{event_type!r} (revision {task_revision})"
                        ),
                    )
                    logger.warning(
                        "Quarantined event type=%s task=%s",
                        event_type,
                        task.get("id"),
                    )
                    continue  # do NOT dispatch
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    @property
    def current_revision(self) -> LifecycleRevision:
        return self._current_revision

    def bump_revision(self) -> None:
        """Advance the revision sequence (called after a state commit)."""
        self._revision_sequence += 1
        self._current_revision = LifecycleRevision(
            attempt=self._current_revision.attempt,
            revision=self._current_revision.revision + 1,
            lifecycle=self._current_revision.lifecycle,
            version=self._current_revision.version,
        )

    def set_version(self, version: str) -> None:
        """Update the engine version (used during rolling upgrades)."""
        self._current_revision = LifecycleRevision(
            attempt=1,
            revision=self._revision_sequence + 1,
            lifecycle="active",
            version=version,
        )

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task.get("target_agent", "")

        # Phase 2: attempt / lifecycle check before execution
        task_revision = LifecycleRevision.from_dict(
            task.get("_revision", {})
        )
        if not task_revision.allowed(self._current_revision):
            self.quarantine.quarantine(
                task,
                reason=f"Revision check failed: {task_revision} vs {self._current_revision}",
            )
            logger.warning(
                "Revision guard blocked task=%s revision=%s current=%s",
                task_id,
                task_revision,
                self._current_revision,
            )
            return

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
