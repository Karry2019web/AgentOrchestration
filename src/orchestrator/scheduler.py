"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional
from uuid import uuid4


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
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._reservations: Dict[str, str] = {}  # task_id -> worker_id
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0, worker_id: Optional[str] = None) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task_id = task["id"]
                task["dequeued_at"] = time.time()
                self._in_flight[task_id] = task
                if worker_id:
                    self._reservations[task_id] = worker_id
                return task
        return None

    def complete(self, task_id: str, worker_id: Optional[str] = None) -> bool:
        if worker_id and task_id in self._reservations:
            if self._reservations[task_id] != worker_id:
                return False
        task = self._in_flight.pop(task_id, None)
        if task:
            self._reservations.pop(task_id, None)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default", worker_id: Optional[str] = None) -> bool:
        if worker_id and task_id in self._reservations:
            if self._reservations[task_id] != worker_id:
                return False
        task = self._in_flight.pop(task_id, None)
        if task:
            self._reservations.pop(task_id, None)
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def reclaim_abandoned(self, worker_id: str, timeout: float = 300.0) -> List[Dict]:
        """Reclaim all in-flight tasks reserved by a disconnected worker.

        Args:
            worker_id: The worker that disconnected.
            timeout: Max seconds a task can stay in-flight before considered abandoned.

        Returns:
            List of re-enqueued task dicts.
        """
        reclaimed = []
        now = time.time()
        abandoned_tids = []
        for tid, wid in list(self._reservations.items()):
            if wid == worker_id:
                task = self._in_flight.get(tid)
                if task and (now - task.get("dequeued_at", now)) >= timeout:
                    abandoned_tids.append(tid)

        for tid in abandoned_tids:
            task = self._in_flight.pop(tid, None)
            if task:
                self._reservations.pop(tid, None)
                task["retries"] += 1
                task["reclaimed_at"] = now
                task["_abandoned"] = True
                if task["retries"] < self._max_retries:
                    self.enqueue(task, "default", priority=task.get("priority", 0))
                    reclaimed.append(task)
        return reclaimed

    def reclaim_all_abandoned(self, timeout: float = 300.0) -> List[Dict]:
        """Reclaim all in-flight tasks that have exceeded the timeout regardless of worker.

        Args:
            timeout: Max seconds a task can stay in-flight without progress.

        Returns:
            List of re-enqueued task dicts.
        """
        reclaimed = []
        now = time.time()
        for tid, task in list(self._in_flight.items()):
            dequeued_at = task.get("dequeued_at", now)
            if now - dequeued_at >= timeout:
                self._in_flight.pop(tid, None)
                self._reservations.pop(tid, None)
                task["retries"] += 1
                task["reclaimed_at"] = now
                task["_abandoned"] = True
                if task["retries"] < self._max_retries:
                    self.enqueue(task, "default", priority=task.get("priority", 0))
                    reclaimed.append(task)
        return reclaimed
