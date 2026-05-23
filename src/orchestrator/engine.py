"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Set

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    """Orchestration engine that coordinates task execution across agents.

    Tracks workflow lifecycle to prevent stale task execution after
    workflow deletion — protects against cleanup races where deleted
    workflows still have in-flight or queued tasks.
    """

    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
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
        # Track deleted workflow IDs so queued tasks are rejected
        self._deleted_workflows: Set[str] = set()

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                if self._is_stale_task(task):
                    logger.warning(
                        "Rejecting stale task %s for deleted workflow %s",
                        task.get("id", "unknown"),
                        task.get("workflow_id", "unknown"),
                    )
                    self.scheduler.complete(task.get("id", ""))
                    continue
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False
        logger.info("Orchestration engine stopped")

    def mark_workflow_deleted(self, workflow_id: str) -> None:
        """Record that a workflow has been deleted so its pending tasks are rejected."""
        self._deleted_workflows.add(workflow_id)
        logger.info("Workflow %s marked as deleted — queued tasks will be rejected", workflow_id)

    def is_workflow_active(self, workflow_id: str) -> bool:
        """Check if a workflow is still active (not deleted)."""
        return workflow_id not in self._deleted_workflows

    def _is_stale_task(self, task: Dict[str, Any]) -> bool:
        """Check if a task belongs to a deleted workflow and should be rejected."""
        workflow_id = task.get("workflow_id")
        if workflow_id and workflow_id in self._deleted_workflows:
            return True
        # Also check if the target agent was deleted
        agent_id = task.get("target_agent")
        if agent_id and not self.registry.get(agent_id):
            return True
        return False

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
