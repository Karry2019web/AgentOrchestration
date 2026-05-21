"""Task Scheduler — Priority-based task queuing and dispatch with idempotent dead-letter handling."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


class DeadLetterRecord:
    """Record for a dead-lettered task with acknowledgement tracking."""
    def __init__(self, task_id: str, task: Dict, reason: str, timestamp: float = None):
        self.task_id = task_id
        self.task = task
        self.reason = reason
        self.timestamp = timestamp or time.time()
        self.acknowledged = False
        self.acknowledged_at: Optional[float] = None


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
        self._dead_letter: Dict[str, DeadLetterRecord] = {}
        self._acked_tasks: Set[str] = set()
        self._max_retries = 3

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        if "id" not in task:
            task["id"] = str(uuid4())
        task["enqueued_at"] = time.time()
        task["retries"] = task.get("retries", 0)

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task["id"]

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()
        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task_data = self._scheduled.pop(tid)
            if task_data:
                self.enqueue(task_data, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        if task_id in self._acked_tasks:
            return True
        task = self._in_flight.pop(task_id, None)
        if task is not None:
            self._acked_tasks.add(task_id)
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        if task_id in self._acked_tasks:
            return False
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                if queue not in self._queues:
                    self._queues[queue] = PriorityQueue()
                self._queues[queue].push(task, priority=task.get("priority", 0))
                return True
            else:
                self._send_to_dead_letter(task, "max_retries_exceeded")
        return False

    def _send_to_dead_letter(self, task: Dict, reason: str) -> None:
        task_id = task["id"]
        if task_id not in self._dead_letter:
            self._dead_letter[task_id] = DeadLetterRecord(
                task_id=task_id, task=task, reason=reason
            )

    def acknowledge_dead_letter(self, task_id: str) -> bool:
        """Acknowledge a dead-lettered task, making all subsequent operations idempotent."""
        record = self._dead_letter.get(task_id)
        if record is None:
            return False
        if record.acknowledged:
            return True
        record.acknowledged = True
        record.acknowledged_at = time.time()
        self._acked_tasks.add(task_id)
        return True

    def retry_dead_letter(self, task_id: str, queue: str = "default") -> bool:
        """Retry a dead-lettered task by re-enqueuing it."""
        if task_id in self._acked_tasks:
            return False
        record = self._dead_letter.pop(task_id, None)
        if record is None:
            return False
        record.task["retries"] = 0
        record.task["dead_letter_retry"] = True
        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(record.task, 0)
        return True

    def list_dead_letter(self) -> List[Dict]:
        """List all dead-lettered tasks with their acknowledgement status."""
        return [
            {
                "task_id": r.task_id,
                "task_type": r.task.get("type", "unknown"),
                "reason": r.reason,
                "timestamp": r.timestamp,
                "acknowledged": r.acknowledged,
            }
            for r in self._dead_letter.values()
        ]

    def dead_letter_count(self) -> Dict[str, int]:
        """Count dead-letter records grouped by reason."""
        counts: Dict[str, int] = {}
        for record in self._dead_letter.values():
            counts[record.reason] = counts.get(record.reason, 0) + 1
        return counts
