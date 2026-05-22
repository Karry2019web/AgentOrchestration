"""Agent Executor — Handles task execution within agent sandboxes."""

import asyncio
import json
import time
from typing import Any, Callable, Dict, Optional, Set
from uuid import uuid4


class JsonSerializationError(Exception):
    """Raised when a tool result cannot be JSON-serialized."""
    pass


class AgentExecutor:
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Any] = {}
        self._finalized: Set[str] = set()

    async def execute(self, agent_id: str, task: Dict[str, Any], handler: Callable) -> str:
        execution_id = str(uuid4())
        async with self._semaphore:
            task_obj = asyncio.create_task(
                self._run_execution(execution_id, agent_id, task, handler)
            )
            self._active_tasks[execution_id] = task_obj
            try:
                result = await task_obj
                # Validate JSON serialization before recording success
                try:
                    json.dumps(result)
                except (TypeError, ValueError) as e:
                    raise JsonSerializationError(
                        f"Tool result for task {task.get('id')} is not JSON-serializable: {e}"
                    )
                # Idempotent: only store if not already finalized
                if execution_id not in self._finalized:
                    self._results[execution_id] = result
                    self._finalized.add(execution_id)
            except JsonSerializationError:
                # Non-JSON result — record one durable terminal failure outcome
                if execution_id not in self._finalized:
                    self._results[execution_id] = {
                        "error": "Tool result is not JSON-serializable",
                        "execution_id": execution_id,
                        "agent_id": agent_id,
                        "task_id": task.get("id"),
                        "timestamp": time.time(),
                    }
                    self._finalized.add(execution_id)
            except Exception as e:
                # Other errors — record once, idempotently
                if execution_id not in self._finalized:
                    self._results[execution_id] = {"error": str(e)}
                    self._finalized.add(execution_id)
            finally:
                self._active_tasks.pop(execution_id, None)
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

    def is_finalized(self, execution_id: str) -> bool:
        """Check if an execution has been finalized idempotently."""
        return execution_id in self._finalized

    async def shutdown(self) -> None:
        for task in self._active_tasks.values():
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks.values(), return_exceptions=True)
