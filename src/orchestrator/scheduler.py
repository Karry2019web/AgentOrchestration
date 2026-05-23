"""Task Scheduler — Priority-based task queuing and dispatch with workspace scope enforcement."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


class WorkspaceScopedStore:
    """In-memory store that enforces workspace scope on all task state operations."""

    def __init__(self):
        self._queues: Dict[str, Dict[str, "PriorityQueue"]] = {}
        self._scheduled: Dict[str, Dict[str, float]] = {}
        self._in_flight: Dict[str, Dict[str, Dict]] = {}
        self._task_workspace: Dict[str, str] = {}

    def enqueue(self, task: Dict, workspace_id: str, queue: str = "default", priority: int = 0) -> str:
        self._validate_workspace(workspace_id)
        task_id = str(uuid4())
        task["id"] = task_id
        task["workspace_id"] = workspace_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        if workspace_id not in self._queues:
            self._queues[workspace_id] = {}
        if queue not in self._queues[workspace_id]:
            self._queues[workspace_id][queue] = PriorityQueue()
        self._queues[workspace_id][queue].push(task, priority)
        self._task_workspace[task_id] = workspace_id
        return task_id

    def schedule(self, task: Dict, workspace_id: str, delay: float) -> str:
        self._validate_workspace(workspace_id)
        task_id = str(uuid4())
        task["id"] = task_id
        task["workspace_id"] = workspace_id
        self._scheduled.setdefault(workspace_id, {})[task_id] = time.time() + delay
        self._task_workspace[task_id] = workspace_id
        return task_id

    async def dequeue(self, workspace_id: str, queue: str = "default") -> Optional[Dict]:
        self._validate_workspace(workspace_id)
        now = time.time()
        ws_scheduled = self._scheduled.get(workspace_id, {})
        expired = [tid for tid, t in ws_scheduled.items() if t <= now]
        for tid in expired:
            task_data = ws_scheduled.pop(tid)
            if task_data:
                self._push_to_queue(task_data, workspace_id, queue)
        ws_queues = self._queues.get(workspace_id, {})
        if queue in ws_queues and len(ws_queues[queue]) > 0:
            task = ws_queues[queue].pop()
            if task:
                self._in_flight.setdefault(workspace_id, {})
                self._in_flight[workspace_id][task["id"]] = task
                return task
        return None

    def complete(self, task_id: str, workspace_id: str) -> bool:
        self._validate_workspace(workspace_id)
        ws_in_flight = self._in_flight.get(workspace_id, {})
        if task_id not in ws_in_flight:
            return False
        ws_in_flight.pop(task_id)
        self._task_workspace.pop(task_id, None)
        return True

    def fail(self, task_id: str, workspace_id: str, queue: str = "default") -> bool:
        self._validate_workspace(workspace_id)
        ws_in_flight = self._in_flight.get(workspace_id, {})
        task = ws_in_flight.pop(task_id, None)
        if task:
            task["retries"] = task.get("retries", 0) + 1
            if task["retries"] < 3:
                self._push_to_queue(task, workspace_id, queue, priority=task.get("priority", 0))
                return True
        return False

    def get_in_flight(self, task_id: str, workspace_id: str) -> Optional[Dict]:
        self._validate_workspace(workspace_id)
        return self._in_flight.get(workspace_id, {}).get(task_id)

    def list_in_flight(self, workspace_id: str) -> List[Dict]:
        self._validate_workspace(workspace_id)
        return list(self._in_flight.get(workspace_id, {}).values())

    def list_scheduled(self, workspace_id: str) -> List[str]:
        self._validate_workspace(workspace_id)
        return list(self._scheduled.get(workspace_id, {}).keys())

    def get_task_workspace(self, task_id: str) -> Optional[str]:
        return self._task_workspace.get(task_id)

    def _validate_workspace(self, workspace_id: str) -> None:
        if not workspace_id or not isinstance(workspace_id, str):
            raise ValueError("workspace_id is required and must be a non-empty string")

    def _push_to_queue(self, task: Dict, workspace_id: str, queue: str, priority: int = 0) -> None:
        if workspace_id not in self._queues:
            self._queues[workspace_id] = {}
        if queue not in self._queues[workspace_id]:
            self._queues[workspace_id][queue] = PriorityQueue()
        self._queues[workspace_id][queue].push(task, priority)


class PriorityQueue:
    def __init__(self):
        self._queue = []
        self._counter = 0

    def push(self, item: Any, priority: int = 0) -> None:
        heapq.heappush(self._queue, (-priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[Any]:
        if self._queue:
            return heapq.heappop(self._queue)[2]
        return None

    def peek(self) -> Optional[Any]:
        if self._queue:
            return self._queue[0][2]
        return None

    def __len__(self) -> int:
        return len(self._queue)


class TaskScheduler:
    """Scoped task scheduler that enforces workspace isolation on all operations."""

    def __init__(self):
        self._store = WorkspaceScopedStore()

    def enqueue(self, task: Dict, workspace_id: str, queue: str = "default", priority: int = 0) -> str:
        return self._store.enqueue(task, workspace_id, queue, priority)

    def schedule(self, task: Dict, workspace_id: str, delay: float) -> str:
        return self._store.schedule(task, workspace_id, delay)

    async def dequeue(self, workspace_id: str, queue: str = "default") -> Optional[Dict]:
        return await self._store.dequeue(workspace_id, queue)

    def complete(self, task_id: str, workspace_id: str) -> bool:
        return self._store.complete(task_id, workspace_id)

    def fail(self, task_id: str, workspace_id: str, queue: str = "default") -> bool:
        return self._store.fail(task_id, workspace_id, queue)

    def get_in_flight(self, task_id: str, workspace_id: str) -> Optional[Dict]:
        return self._store.get_in_flight(task_id, workspace_id)

    def list_in_flight(self, workspace_id: str) -> List[Dict]:
        return self._store.list_in_flight(workspace_id)

    def list_scheduled(self, workspace_id: str) -> List[str]:
        return self._store.list_scheduled(workspace_id)

    def get_task_workspace(self, task_id: str) -> Optional[str]:
        return self._store.get_task_workspace(task_id)
