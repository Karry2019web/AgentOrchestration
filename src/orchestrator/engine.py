"""Orchestration Engine — Core execution and coordination logic."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.lock_manager import LockManager, LockNotAcquiredError
from src.orchestrator.scheduler import TaskScheduler

logger = logging.getLogger(__name__)


class OrchestrationEngine:
    def __init__(
        self,
        max_workers: int = 10,
        agent_timeout: int = 300,
        db_dsn: str = "",
        lock_retries: int = 3,
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
        # Initialize the lock manager for distributed task coordination
        self.lock_manager = LockManager(
            dsn=db_dsn,
            max_retries=lock_retries,
        )

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

        # Acquire an advisory lock scoped to this task to prevent duplicate execution.
        # The lock is automatically released on exception via the finally block below.
        lock_key = f"task:{task_id}"
        task_lock = None
        try:
            task_lock = self.lock_manager.acquire(lock_key, task_id=task_id)
        except LockNotAcquiredError:
            logger.warning(
                "Task %s could not acquire lock (already in progress), skipping", task_id
            )
            for hook in self._hooks["on_error"]:
                await hook(task, LockNotAcquiredError("Task already locked"))
            return
        except Exception as lock_err:
            logger.warning(
                "Task %s lock acquisition error (non-fatal): %s", task_id, lock_err
            )

        try:
            for hook in self._hooks["pre_execute"]:
                await hook(task)

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

        finally:
            # Critical: always release the advisory lock, even on exception.
            # This prevents lock leaks when task execution raises an exception.
            if task_lock is not None and not task_lock.is_released:
                try:
                    self.lock_manager.release(lock_key)
                    logger.debug("Released advisory lock for task %s", task_id)
                except Exception as release_err:
                    logger.error(
                        "Failed to release advisory lock for task %s: %s",
                        task_id, release_err,
                    )

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

    def close(self) -> None:
        """Clean up resources including the lock manager connection pool."""
        self.lock_manager.close()
        self.executor.shutdown(wait=True)
        logger.info("Orchestration engine resources cleaned up")
