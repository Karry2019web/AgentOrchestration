"""Orchestration Engine — Core execution and coordination logic with lease management."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.metrics import metrics
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
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
        self._lease_renewal_task: Optional[asyncio.Task] = None

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self._hooks:
            self._hooks[event].append(callback)

    async def start(self) -> None:
        self._running = True
        self._lease_renewal_task = asyncio.create_task(self._lease_renewal_loop())
        logger.info("Orchestration engine started")
        while self._running:
            task = await self.scheduler.dequeue()
            if task:
                asyncio.create_task(self._execute_task(task))
            await asyncio.sleep(0.1)

    async def _lease_renewal_loop(self) -> None:
        """Periodically renew leases for tasks in upload state."""
        while self._running:
            try:
                for task_id in list(self.scheduler._uploading.keys()):
                    self.scheduler.renew_lease(task_id)
                    metrics.increment("lease.renewal")
                    logger.debug("Auto-renewed lease for uploading task %s", task_id)
                recovered = self.scheduler.recover_expired_leases()
                if recovered:
                    metrics.increment("lease.recovery", len(recovered))
                    logger.info("Recovered %d expired leases", len(recovered))
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Lease renewal loop error: %s", e)
                await asyncio.sleep(5)

    def stop(self) -> None:
        self._running = False
        if self._lease_renewal_task:
            self._lease_renewal_task.cancel()
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
