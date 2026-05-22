"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class RunStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"
    CANCELLED = "cancelled"


class RunState:
    """Tracks the lifecycle state of a single run."""

    def __init__(self, run_id: str, workflow_id: str):
        self.run_id = run_id
        self.workflow_id = workflow_id
        self.status = RunStatus.PENDING
        self.version = 0
        self.created_at = time.time()
        self.updated_at = time.time()
        self.events: List[Dict] = []

    def transition_to(self, new_status: RunStatus) -> bool:
        valid_transitions = {
            RunStatus.PENDING: [RunStatus.RUNNING, RunStatus.CANCELLED],
            RunStatus.RUNNING: [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED],
            RunStatus.COMPLETED: [RunStatus.ARCHIVED],
            RunStatus.FAILED: [RunStatus.ARCHIVED],
            RunStatus.ARCHIVED: [],
            RunStatus.CANCELLED: [RunStatus.ARCHIVED],
        }
        allowed = valid_transitions.get(self.status, [])
        if new_status not in allowed:
            return False
        self.status = new_status
        self.version += 1
        self.updated_at = time.time()
        return True

    def is_terminal(self) -> bool:
        return self.status in (RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ARCHIVED, RunStatus.CANCELLED)

    def is_archived(self) -> bool:
        return self.status == RunStatus.ARCHIVED


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._runs: Dict[str, RunState] = {}
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }

    def create_run(self, workflow_id: str) -> str:
        run_id = str(uuid4())
        self._runs[run_id] = RunState(run_id, workflow_id)
        return run_id

    def get_run_status(self, run_id: str) -> Optional[str]:
        run = self._runs.get(run_id)
        return run.status.value if run else None

    def archive_run(self, run_id: str) -> bool:
        run = self._runs.get(run_id)
        if not run:
            return False
        return run.transition_to(RunStatus.ARCHIVED)

    def dispatch_event(self, run_id: str, event: Dict[str, Any]) -> bool:
        """Dispatch an event to a run, rejecting events for archived runs."""
        run = self._runs.get(run_id)
        if not run:
            logger.warning(f"Run {run_id} not found — rejecting event")
            return False

        if run.is_archived():
            logger.warning(
                f"Rejecting event for archived run {run_id} "
                f"(status={run.status.value}, version={run.version})"
            )
            return False

        if run.is_terminal():
            logger.warning(
                f"Rejecting event for terminal run {run_id} "
                f"(status={run.status.value}, version={run.version})"
            )
            return False

        event_record = {
            "event_id": str(uuid4()),
            "timestamp": time.time(),
            "run_id": run_id,
            "run_version": run.version,
            "run_status": run.status.value,
            "payload": event,
        }
        run.events.append(event_record)
        run.updated_at = time.time()
        logger.info(f"Event dispatched to run {run_id} (version={run.version})")
        return True

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
