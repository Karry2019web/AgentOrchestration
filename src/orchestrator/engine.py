"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class DelegationDepthError(Exception):
    """Raised when recursive agent delegation exceeds the configured maximum depth."""
    pass


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300, max_delegation_depth: int = 5):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self.max_delegation_depth = max_delegation_depth
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

    async def _execute_task(self, task: Dict[str, Any]) -> None:
        task_id = task["id"]
        agent_id = task["target_agent"]
        logger.info(f"Executing task {task_id} on agent {agent_id}")

        # Enforce recursive delegation depth bound
        delegation_depth = task.get("delegation_depth", 0)
        if delegation_depth >= self.max_delegation_depth:
            error_msg = (
                f"Task {task_id} rejected: delegation depth {delegation_depth} "
                f"exceeds maximum of {self.max_delegation_depth}"
            )
            logger.error(error_msg)
            for hook in self._hooks["on_error"]:
                await hook(task, DelegationDepthError(error_msg))
            return

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

    def delegate(self, task: Dict[str, Any], target_agent: str) -> str:
        """Submit a delegated task, incrementing the delegation depth.

        Args:
            task: The task to delegate. Must include an "id" field.
            target_agent: The agent to delegate to.

        Returns:
            The task ID of the delegated task.

        Raises:
            DelegationDepthError: If the delegation would exceed the configured depth.
        """
        current_depth = task.get("delegation_depth", 0)
        new_depth = current_depth + 1
        if new_depth > self.max_delegation_depth:
            raise DelegationDepthError(
                f"Cannot delegate task {task.get('id', 'unknown')} to {target_agent}: "
                f"delegation depth {new_depth} exceeds maximum of {self.max_delegation_depth}"
            )
        delegated = dict(task)
        delegated["target_agent"] = target_agent
        delegated["delegation_depth"] = new_depth
        return self.scheduler.enqueue(delegated)
