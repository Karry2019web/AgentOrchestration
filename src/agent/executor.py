"""Agent Executor — Handles task execution within agent sandboxes."""

import asyncio
import time
from typing import Any, Callable, Dict, Optional
from uuid import uuid4


class AgentExecutor:
    def __init__(
        self,
        max_concurrent: int = 5,
        max_results: int = 1000,
        result_ttl: float = 3600.0,
    ):
        self.max_concurrent = max_concurrent
        self.max_results = max_results
        self.result_ttl = result_ttl
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._result_timestamps: Dict[str, float] = {}

    def _cleanup_stale_results(self) -> None:
        """Remove stale results exceeding TTL or max_results cap."""
        now = time.time()

        # 1. Evict entries past their TTL
        stale_keys = [
            k
            for k, ts in self._result_timestamps.items()
            if now - ts > self.result_ttl
        ]
        for k in stale_keys:
            self._results.pop(k, None)
            self._result_timestamps.pop(k, None)

        # 2. If still over max_results, drop oldest entries
        if len(self._results) > self.max_results:
            excess = len(self._results) - self.max_results
            sorted_keys = sorted(
                self._result_timestamps, key=self._result_timestamps.get
            )
            for k in sorted_keys[:excess]:
                self._results.pop(k, None)
                self._result_timestamps.pop(k, None)

    async def execute(
        self, agent_id: str, task: Dict[str, Any], handler: Callable
    ) -> str:
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

        self._cleanup_stale_results()
        return execution_id

    async def _run_execution(
        self, exec_id: str, agent_id: str, task: Dict, handler: Callable
    ) -> Any:
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
            await asyncio.gather(
                *self._active_tasks.values(), return_exceptions=True
            )
