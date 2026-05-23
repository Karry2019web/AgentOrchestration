"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from threading import Lock
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


class LeaderEpoch:
    """Idempotent leader epoch tracker for tick deduplication.

    Each time the leader changes, increment the epoch.  Cron ticks carry
    the epoch they were emitted in; ticks with a stale epoch are rejected
    by the scheduler to prevent duplicate work during leader transitions.
    """

    def __init__(self):
        self._lock = Lock()
        self._epoch = 0
        self._ledger: Dict[str, int] = {}  # tick_id -> epoch

    @property
    def epoch(self) -> int:
        with self._lock:
            return self._epoch

    def advance(self) -> int:
        with self._lock:
            self._epoch += 1
            return self._epoch

    def witness(self, tick_id: str, tick_epoch: int) -> bool:
        """Register a cron tick.

        Returns ``True`` if the tick is accepted (epoch matches current),
        ``False`` if it is a duplicate or stale tick that should be dropped.
        """
        with self._lock:
            if tick_epoch != self._epoch:
                return False
            if tick_id in self._ledger:
                return False
            self._ledger[tick_id] = tick_epoch
            return True

    def prune(self, older_than_epoch: int) -> int:
        """Remove ledger entries for epochs older than *older_than_epoch*.

        Returns the number of pruned entries.
        """
        with self._lock:
            before = len(self._ledger)
            self._ledger = {tid: ep for tid, ep in self._ledger.items()
                           if ep >= older_than_epoch}
            return before - len(self._ledger)


class TaskScheduler:
    def __init__(self):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._leader_epoch = LeaderEpoch()

    @property
    def leader_epoch(self) -> LeaderEpoch:
        return self._leader_epoch

    def advance_leader_epoch(self) -> int:
        """Signal a leader election change and return the new epoch."""
        return self._leader_epoch.advance()

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

    def emit_cron_tick(self, tick_id: str) -> bool:
        """Emit a cron tick that is deduplicated across leader epochs.

        Returns ``True`` if the tick was accepted, ``False`` if it was
        rejected as stale or duplicate (during a leader transition).
        """
        return self._leader_epoch.witness(tick_id, self._leader_epoch.epoch)

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
                self._in_flight[task["id"]] = task
                return task
        return None

    def complete(self, task_id: str) -> bool:
        return self._in_flight.pop(task_id, None) is not None

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if task:
            task["retries"] += 1
            if task["retries"] < self._max_retries:
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

# 2026-05-23T23:52:00+08:00 update
