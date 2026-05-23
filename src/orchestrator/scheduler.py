"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from typing import Any, Dict, List, Optional, Tuple
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
        self._processing_times: Dict[str, List[float]] = {}
        self._lease_renewal_attempts: int = 0
        self._lease_renewal_failures: int = 0

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
                task["dequeued_at"] = time.time()
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            enqueued = task.get("enqueued_at", 0)
            dequeued = task.get("dequeued_at", 0)
            if enqueued > 0 and dequeued > 0:
                latency = dequeued - enqueued
                queue_name = "default"
                if queue_name not in self._processing_times:
                    self._processing_times[queue_name] = []
                self._processing_times[queue_name].append(latency)
                # Keep only last 1000 samples
                if len(self._processing_times[queue_name]) > 1000:
                    self._processing_times[queue_name] = self._processing_times[queue_name][-1000:]
            return True
        return False

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    def record_lease_renewal(self, success: bool) -> None:
        self._lease_renewal_attempts += 1
        if not success:
            self._lease_renewal_failures += 1

    def get_queue_depth(self) -> Dict[str, int]:
        """Return the current backlog depth per queue."""
        return {name: len(q) for name, q in self._queues.items()}

    def get_total_backlog(self) -> int:
        """Return total pending tasks across all queues."""
        return sum(len(q) for q in self._queues.values())

    def get_in_flight_count(self) -> int:
        """Return number of tasks currently being processed."""
        return len(self._in_flight)

    def get_average_latency(self) -> Dict[str, float]:
        """Return average processing latency (enqueue to dequeue) per queue."""
        latencies = {}
        for queue_name, times in self._processing_times.items():
            if times:
                latencies[queue_name] = sum(times) / len(times)
            else:
                latencies[queue_name] = 0.0
        return latencies

    def get_lease_renewal_metrics(self) -> Tuple[int, int]:
        """Return (attempts, failures) for lease renewals."""
        return self._lease_renewal_attempts, self._lease_renewal_failures

    def get_metrics_snapshot(self) -> Dict:
        """Return a complete metrics snapshot for canary analysis."""
        depths = self.get_queue_depth()
        latencies = self.get_average_latency()
        return {
            "queue_depth": depths,
            "total_backlog": self.get_total_backlog(),
            "in_flight": self.get_in_flight_count(),
            "average_latency": latencies,
            "lease_renewal_attempts": self._lease_renewal_attempts,
            "lease_renewal_failures": self._lease_renewal_failures,
        }
