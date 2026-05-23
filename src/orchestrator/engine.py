"""Orchestration Engine — Core execution and coordination logic with workspace scope."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(self, max_workers: int = 10, agent_timeout: int = 300):
        self.registry = AgentRegistry()
        self.scheduler = TaskScheduler()
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.agent_timeout = agent_timeout
        self._running = False
        self._current_workspace: Optional[str] = None
        self._hooks: Dict[str, List[Callable]] = {
            "pre_execute": [],
            "post_execute": [],
            "on_error": [],
            "on_complete": [],
        }

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    def set_workspace(self, workspace_id: str) -> None:
        if not workspace_id or not isinstance(workspace_id, str):
            raise ValueError("workspace_id is required")
        self._current_workspace = workspace_id

    def get_workspace(self) -> Optional[str]:
        return self._current_workspace

    async def start(self) -> None:
        self._running = True
        logger.info("Orchestration engine started")
        while self._running:
            ws = self._current_workspace or "default"
            task = await self.scheduler.dequeue(workspace_id=ws)
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

    def enqueue_task(self, task: Dict, workspace_id: Optional[str] = None,
                     queue: str = "default", priority: int = 0) -> str:
        ws = workspace_id or self._current_workspace or "default"
        return self.scheduler.enqueue(task, ws, queue, priority)

    def complete_task(self, task_id: str, workspace_id: Optional[str] = None) -> bool:
        ws = workspace_id or self._current_workspace or "default"
        return self.scheduler.complete(task_id, ws)

    def fail_task(self, task_id: str, workspace_id: Optional[str] = None,
                  queue: str = "default") -> bool:
        ws = workspace_id or self._current_workspace or "default"
        return self.scheduler.fail(task_id, ws, queue)
