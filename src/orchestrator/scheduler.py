"""Task Scheduler — Priority-based task queuing and dispatch with limiter audit."""

import asyncio
import heapq
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


class Decision(Enum):
    ALLOWED = "allowed"
    REJECTED = "rejected"
    DEFERRED = "deferred"


@dataclass
class AuditEntry:
    """Bounded, sanitized record of a limiter decision."""
    timestamp: str
    decision: str
    reason: str
    queue: str
    task_id: Optional[str] = None
    priority: int = 0
    in_flight_count: int = 0
    queue_depth: int = 0
    max_capacity: int = 0

    def sanitize(self) -> "AuditEntry":
        """Return a copy with no private runtime data."""
        return AuditEntry(
            timestamp=self.timestamp,
            decision=self.decision,
            reason=self.reason,
            queue=self.queue,
            task_id=None,
            priority=0,
            in_flight_count=self.in_flight_count,
            queue_depth=self.queue_depth,
            max_capacity=self.max_capacity,
        )


class LimiterAuditLog:
    """Ring-buffer audit log of bounded capacity."""

    def __init__(self, max_entries: int = 1000):
        self._entries: List[AuditEntry] = []
        self._max = max_entries

    def record(self, entry: AuditEntry) -> None:
        sanitized = entry.sanitize()
        self._entries.append(sanitized)
        if len(self._entries) > self._max:
            self._entries.pop(0)

    def recent(self, n: int = 50) -> List[dict]:
        return [asdict(e) for e in self._entries[-n:]]

    @property
    def total_rejected(self) -> int:
        return sum(1 for e in self._entries if e.decision == Decision.REJECTED.value)

    @property
    def total_deferred(self) -> int:
        return sum(1 for e in self._entries if e.decision == Decision.DEFERRED.value)

    def __len__(self) -> int:
        return len(self._entries)


class CapacityLimiter:
    """Per-queue capacity checks with audit trail."""

    def __init__(self, audit: LimiterAuditLog, default_max_in_flight: int = 100):
        self._audit = audit
        self._max_in_flight: Dict[str, int] = {}
        self._max_queue_depth: Dict[str, int] = {}
        self._rate_limit: Dict[str, float] = {}
        self._last_dequeue_time: Dict[str, float] = {}

    def set_max_in_flight(self, queue: str, limit: int) -> None:
        self._max_in_flight[queue] = limit

    def set_max_queue_depth(self, queue: str, limit: int) -> None:
        self._max_queue_depth[queue] = limit

    def set_rate_limit(self, queue: str, min_interval: float) -> None:
        self._rate_limit[queue] = min_interval

    def check_can_enqueue(
        self, queue: str, current_depth: int, priority: int = 0
    ) -> Tuple[Decision, str]:
        now = _now_iso()
        max_depth = self._max_queue_depth.get(queue, 5000)

        if current_depth >= max_depth:
            entry = AuditEntry(
                timestamp=now, decision=Decision.REJECTED.value,
                reason=f"Queue depth {current_depth} >= max {max_depth}",
                queue=queue, priority=priority,
                queue_depth=current_depth, max_capacity=max_depth,
            )
            self._audit.record(entry)
            return Decision.REJECTED, f"queue {queue} at capacity ({current_depth}/{max_depth})"

        entry = AuditEntry(
            timestamp=now, decision=Decision.ALLOWED.value,
            reason="queue depth within limits",
            queue=queue, priority=priority,
            queue_depth=current_depth, max_capacity=max_depth,
        )
        self._audit.record(entry)
        return Decision.ALLOWED, ""

    def check_can_dequeue(
        self, queue: str, in_flight_count: int
    ) -> Tuple[Decision, str]:
        now = _now_iso()
        max_in_flight = self._max_in_flight.get(queue, 500)

        if in_flight_count >= max_in_flight:
            entry = AuditEntry(
                timestamp=now, decision=Decision.DEFERRED.value,
                reason=f"In-flight {in_flight_count} >= max {max_in_flight}",
                queue=queue, in_flight_count=in_flight_count,
                max_capacity=max_in_flight,
            )
            self._audit.record(entry)
            return Decision.DEFERRED, f"in-flight capacity reached ({in_flight_count}/{max_in_flight})"

        min_interval = self._rate_limit.get(queue, 0.0)
        if min_interval > 0:
            last = self._last_dequeue_time.get(queue, 0.0)
            elapsed = time.time() - last
            if elapsed < min_interval:
                entry = AuditEntry(
                    timestamp=now, decision=Decision.DEFERRED.value,
                    reason=f"Rate limit: {elapsed:.2f}s < {min_interval}s interval",
                    queue=queue, in_flight_count=in_flight_count,
                )
                self._audit.record(entry)
                return Decision.DEFERRED, f"rate limited ({elapsed:.2f}s < {min_interval}s)"

        entry = AuditEntry(
            timestamp=now, decision=Decision.ALLOWED.value,
            reason="capacity available",
            queue=queue, in_flight_count=in_flight_count,
            max_capacity=max_in_flight,
        )
        self._audit.record(entry)
        return Decision.ALLOWED, ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        self.audit_log = LimiterAuditLog()
        self.limiter = CapacityLimiter(self.audit_log)

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> Optional[str]:
        current_depth = len(self._queues.get(queue, PriorityQueue()))
        decision, reason = self.limiter.check_can_enqueue(queue, current_depth, priority)

        if decision != Decision.ALLOWED:
            logger.warning("enqueue rejected for queue %s: %s", queue, reason)
            return None

        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> Optional[str]:
        current_depth = len(self._queues.get(queue, PriorityQueue()))
        decision, reason = self.limiter.check_can_enqueue(queue, current_depth, priority)

        if decision != Decision.ALLOWED:
            logger.warning("schedule rejected for queue %s: %s", queue, reason)
            return None

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

        in_flight_count = len(self._in_flight)
        decision, reason = self.limiter.check_can_dequeue(queue, in_flight_count)

        if decision != Decision.ALLOWED:
            logger.debug("dequeue deferred for queue %s: %s", queue, reason)
            return None

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

    def get_audit_trail(self, n: int = 50) -> List[dict]:
        """Public accessor for troubleshooting / capacity analysis."""
        return self.audit_log.recent(n)
