"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, Optional
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
        self._max_retries = 3
        self._workers: Dict[str, float] = {}
        self._worker_tasks: Dict[str, set] = {}

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

    async def dequeue(self, queue: str = "default", timeout: float = 1.0,
                      worker_id: Optional[str] = None) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                task["dequeued_at"] = time.time()
                self._in_flight[task["id"]] = task
                if worker_id:
                    task["assigned_worker"] = worker_id
                    if worker_id not in self._worker_tasks:
                        self._worker_tasks[worker_id] = set()
                    self._worker_tasks[worker_id].add(task["id"])
                return task
        return None

    def complete(self, task_id: str, worker_id: Optional[str] = None) -> bool:
        task = self._in_flight.get(task_id)
        if not task:
            return False
        if worker_id and task.get("assigned_worker") and task["assigned_worker"] != worker_id:
            return False
        self._in_flight.pop(task_id, None)
        w = task.get("assigned_worker")
        if w and w in self._worker_tasks:
            self._worker_tasks[w].discard(task_id)
        return True

    def fail(self, task_id: str, queue: str = "default", worker_id: Optional[str] = None) -> bool:
        task = self._in_flight.get(task_id)
        if not task:
            return False
        if worker_id and task.get("assigned_worker") and task["assigned_worker"] != worker_id:
            return False
        self._in_flight.pop(task_id, None)
        w = task.get("assigned_worker")
        if w and w in self._worker_tasks:
            self._worker_tasks[w].discard(task_id)
        task["retries"] += 1
        if task["retries"] < self._max_retries:
            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        return False

    def worker_heartbeat(self, worker_id: str) -> None:
        self._workers[worker_id] = time.time()

    def deregister_worker(self, worker_id: str) -> int:
        self._workers.pop(worker_id, None)
        abandoned = self._worker_tasks.pop(worker_id, set())
        count = 0
        for task_id in abandoned:
            task = self._in_flight.pop(task_id, None)
            if task:
                task["retries"] += 1
                if task["retries"] < self._max_retries:
                    self.enqueue(task, "default", priority=task.get("priority", 0))
                count += 1
        return count

    def reclaim_abandoned(self, reservation_timeout: float = 300.0, queue: str = "default") -> int:
        now = time.time()
        reclaimed = 0
        stale_workers = set()
        for wid, last_beat in list(self._workers.items()):
            if now - last_beat > reservation_timeout:
                stale_workers.add(wid)
        for wid in stale_workers:
            reclaimed += self.deregister_worker(wid)
        for task_id, task in list(self._in_flight.items()):
            if task.get("assigned_worker") and task["assigned_worker"] not in self._workers:
                dequeued = task.get("dequeued_at", 0)
                if now - dequeued > reservation_timeout:
                    self._in_flight.pop(task_id, None)
                    task["retries"] += 1
                    if task["retries"] < self._max_retries:
                        self.enqueue(task, queue, priority=task.get("priority", 0))
                        task["reclaimed"] = True
                    reclaimed += 1
        return reclaimed

    def get_worker_count(self) -> int:
        return len(self._workers)

    def get_in_flight_count(self) -> int:
        return len(self._in_flight)
