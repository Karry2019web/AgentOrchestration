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
        self._poison_cooldowns: Dict[str, float] = {}  # task_id -> cooldown_until
        self._poison_dead_letters: Dict[str, Dict] = {}  # permanently rejected tasks
        self._max_retries = 3
        self._poison_threshold = 3  # consecutive fails before throttling
        self._poison_cooldown_base = 30.0  # base cooldown in seconds
        self._poison_cooldown_max = 3600.0  # max cooldown

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["_poison_strikes"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
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
                task["dequeued_at"] = now

                # Check if this task is in poison cooldown
                if task_id in self._poison_cooldowns:
                    if now < self._poison_cooldowns[task_id]:
                        # Still in cooldown, put it back
                        self._queues[queue].push(task, task.get("priority", 0))
                        return None
                    else:
                        # Cooldown expired, clear it
                        del self._poison_cooldowns[task_id]

                self._in_flight[task_id] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            # Success resets poison strikes
            task["_poison_strikes"] = 0
            self._poison_cooldowns.pop(task_id, None)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            task["_poison_strikes"] = task.get("_poison_strikes", 0) + 1

            if task["retries"] >= self._max_retries:
                # Max retries exhausted, send to dead letter
                self._poison_dead_letters[task_id] = task
                return False

            strikes = task["_poison_strikes"]
            if strikes >= self._poison_threshold:
                # Enter poison cooldown
                delay = min(
                    self._poison_cooldown_base * (2 ** (strikes - self._poison_threshold)),
                    self._poison_cooldown_max
                )
                self._poison_cooldowns[task_id] = time.time() + delay
                # Schedule a delayed re-enqueue
                task["_poison_delayed_until"] = self._poison_cooldowns[task_id]

            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        return False

    def is_poisoned(self, task_id: str) -> bool:
        """Check if a task is currently in poison cooldown."""
        if task_id in self._poison_cooldowns:
            return time.time() < self._poison_cooldowns[task_id]
        return False

    def dead_letter_count(self) -> int:
        return len(self._poison_dead_letters)

    def list_dead_letters(self) -> list:
        return list(self._poison_dead_letters.values())
