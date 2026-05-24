"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


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


class ReconciliationAudit:
    """Bounded audit record for reconciliation decisions."""

    def __init__(self, max_entries: int = 100):
        self._entries: List[Dict[str, Any]] = []
        self._max_entries = max_entries

    def record(self, decision: str, queue: str, task_count: int, reason: str) -> None:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision": decision,
            "queue": queue,
            "task_count": task_count,
            "reason": reason,
        }
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)

    def recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._entries[-limit:]

    def __len__(self) -> int:
        return len(self._entries)


class ClusterStartupGuard:
    """Atomic state precondition — prevents duplicate or policy-violating
    transitions during cluster startup."""

    def __init__(self):
        self._started = False
        self._started_at: Optional[float] = None
        self._stagger_window: float = 5.0

    def try_acquire(self) -> bool:
        if self._started:
            return False
        self._started = True
        self._started_at = time.time()
        return True

    def is_stable(self) -> bool:
        if not self._started:
            return False
        return (time.time() - self._started_at) >= self._stagger_window

    def reset(self) -> None:
        self._started = False
        self._started_at = None

    @property
    def elapsed(self) -> float:
        if not self._started_at:
            return 0.0
        return time.time() - self._started_at


class TaskScheduler:
    def __init__(self, stagger_min: float = 1.0, stagger_max: float = 5.0):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._running = False
        self._stagger_min = stagger_min
        self._stagger_max = stagger_max
        self._startup_guard = ClusterStartupGuard()
        self._audit = ReconciliationAudit()
        self._reconciliation_task: Optional[asyncio.Task] = None

    @property
    def audit(self) -> ReconciliationAudit:
        return self._audit

    @property
    def startup_guard(self) -> ClusterStartupGuard:
        return self._startup_guard

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
            task_data = self._scheduled.pop(tid, None)
            if task_data is not None:
                self.enqueue(task_data, queue)

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
                # Re-enqueue with backoff
                backoff = 2 ** task["retries"]
                task["_backoff_until"] = time.time() + backoff
                self.enqueue(task, queue, priority=task.get("priority", 0))
                return True
        return False

    async def start_reconciliation(self) -> None:
        """Start the staggered periodic reconciliation loop."""
        if self._running:
            logger.warning("Reconciliation already running")
            return

        if not self._startup_guard.try_acquire():
            logger.warning("Startup guard already acquired — deferring reconciliation")
            return

        self._running = True
        self._reconciliation_task = asyncio.create_task(self._reconciliation_loop())
        logger.info("Reconciliation loop started with stagger window %.1fs",
                     self._startup_guard._stagger_window)
        self._audit.record(
            decision="started",
            queue="__system__",
            task_count=sum(len(q) for q in self._queues.values()),
            reason="reconciliation_loop_started"
        )

    async def stop_reconciliation(self) -> None:
        """Stop the reconciliation loop."""
        self._running = False
        if self._reconciliation_task:
            self._reconciliation_task.cancel()
            self._reconciliation_task = None
        logger.info("Reconciliation loop stopped")

    async def _reconciliation_loop(self) -> None:
        """Periodic reconciliation with staggered timing to avoid
        thundering herd on cluster startup."""
        cycle = 0
        while self._running:
            if not self._startup_guard.is_stable():
                # Stagger phase — random delay within window
                jitter = random.uniform(self._stagger_min, self._stagger_max)
                logger.debug("Cluster startup phase — staggering %.2fs", jitter)
                await asyncio.sleep(jitter)
                continue

            # Stable phase — fixed interval with bounded jitter
            await self._reconcile_once(cycle)
            cycle += 1
            base_interval = 30.0  # seconds between reconciliation cycles
            jitter = random.uniform(0, 5.0)
            await asyncio.sleep(base_interval + jitter)

    async def _reconcile_once(self, cycle: int) -> None:
        """Single reconciliation pass with audit logging."""
        now = time.time()

        # 1. Promote expired scheduled tasks to queues
        expired = [tid for tid, t in list(self._scheduled.items()) if t <= now]
        promoted = 0
        for tid in expired:
            task_data = self._scheduled.pop(tid, None)
            if task_data is not None:
                self.enqueue(task_data, "default")
                promoted += 1

        # 2. Check for stale in-flight tasks (orphaned >60s)
        stale = [tid for tid, t in list(self._in_flight.items())
                 if t.get("enqueued_at", 0) < now - 60]
        reclaimed = 0
        for tid in stale:
            task_data = self._in_flight.pop(tid, None)
            if task_data:
                task_data["retries"] = task_data.get("retries", 0) + 1
                if task_data["retries"] < self._max_retries:
                    self.enqueue(task_data, "default")
                    reclaimed += 1

        # 3. Audit record
        total_queued = sum(len(q) for q in self._queues.values())
        total_scheduled = len(self._scheduled)
        total_in_flight = len(self._in_flight)

        self._audit.record(
            decision="reconcile",
            queue="all",
            task_count=total_queued + total_scheduled + total_in_flight,
            reason=f"cycle={cycle} promoted={promoted} reclaimed={reclaimed} "
                   f"queued={total_queued} scheduled={total_scheduled} in_flight={total_in_flight}"
        )

        if promoted > 0 or reclaimed > 0:
            logger.info("Reconciliation cycle %d: promoted=%d reclaimed=%d",
                        cycle, promoted, reclaimed)
