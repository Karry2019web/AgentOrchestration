"""Agent Executor — Handles task execution within agent sandboxes."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


class AgentExecutor:
    def __init__(self, max_concurrent: int = 5, max_results: int = 1000, result_ttl: float = 3600.0):
        self.max_concurrent = max_concurrent
        self.max_results = max_results
        self.result_ttl = result_ttl
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._result_timestamps: Dict[str, float] = {}

    def _enforce_results_limit(self) -> None:
        """Remove stale results when the result store exceeds max_results or contains expired entries."""
        now = time.time()

        # Prune expired entries by TTL
        expired = [
            exec_id for exec_id, ts in self._result_timestamps.items()
            if now - ts > self.result_ttl
        ]
        for exec_id in expired:
            self._results.pop(exec_id, None)
            self._result_timestamps.pop(exec_id, None)

        # If still over max_results, remove the oldest entries
        if len(self._results) > self.max_results:
            sorted_ids = sorted(
                self._result_timestamps.keys(),
                key=lambda eid: self._result_timestamps[eid],
            )
            excess = len(self._results) - self.max_results
            for exec_id in sorted_ids[:excess]:
                self._results.pop(exec_id, None)
                self._result_timestamps.pop(exec_id, None)

    async def execute(self, agent_id: str, task: Dict[str, Any], handler: Callable) -> str:
        execution_id = str(uuid4())
        async with self._semaphore:
            task_obj = asyncio.create_task(
                self._run_execution(execution_id, agent_id, task, handler)
            )
            self._active_tasks[execution_id] = task_obj
            try:
                result = await task_obj
                self._results[execution_id] = result
                self._result_timestamps[execution_id] = time.time()
            except Exception as e:
                self._results[execution_id] = {"error": str(e)}
                self._result_timestamps[execution_id] = time.time()
            finally:
                self._active_tasks.pop(execution_id, None)
                self._enforce_results_limit()
        return execution_id

    async def _run_execution(self, exec_id: str, agent_id: str, task: Dict, handler: Callable) -> Any:
        start = time.time()
        result = await handler(agent_id, task)
        duration = time.time() - start
        return {
            "execution_id": exec_id,
            "agent_id": agent_id,
            "task_id": task.get("id"),
            "result": result,
            "duration": duration,
            "timestamp": time.time(),
        }

    def get_result(self, execution_id: str) -> Optional[Any]:
        return self._results.get(execution_id)

    def cancel(self, execution_id: str) -> bool:
        task = self._active_tasks.get(execution_id)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def shutdown(self) -> None:
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
        self._results.clear()
        self._result_timestamps.clear()

    def result_count(self) -> int:
        """Return the number of stored results."""
        return len(self._results)
