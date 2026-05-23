"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import hashlib
import heapq
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from uuid import uuid4
from threading import Lock


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


@dataclass
class ReconciliationAuditEntry:
    """Bounded audit record for a reconciliation decision.
    
    Records only timestamp, node ID, action, and reason — no task payloads,
    tokens, or private runtime data.
    """
    timestamp: float
    node_id: str
    action: str          # "accepted", "deferred", "rejected"
    reason: str          # human-readable explanation without private data


@dataclass
class JitterConfig:
    """Configuration for staggered periodic reconciliation at cluster startup.
    
    Attributes:
        stagger_window: Total window (seconds) over which to spread first 
            reconciliation across nodes. Default 60 s.
        base_interval: Nominal interval (seconds) between reconciliations.
            Subsequent runs enforce at least this gap. Default 300 s.
        max_audit_entries: Bounded size of the ring-buffer audit log.
            Default 256.
        node_id: Unique identifier for this scheduler instance. Auto-generated
            from a UUID if not provided.
    """
    stagger_window: float = 60.0
    base_interval: float = 300.0
    max_audit_entries: int = 256
    node_id: str = ""


class TaskScheduler:
    def __init__(self, jitter_config: Optional[JitterConfig] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3

        # --- Reconciliation stagger support ---
        self._jitter_config = jitter_config or JitterConfig()
        if not self._jitter_config.node_id:
            self._jitter_config.node_id = str(uuid4())
        self._periodic_tasks: Dict[str, Tuple[Callable, float, float]] = {}
        self._audit_log: deque = deque(maxlen=self._jitter_config.max_audit_entries)
        self._last_reconcile_time: float = 0.0
        self._reconcile_lock = Lock()
        self._startup_time: float = time.time()

        # Deterministic jitter offset from node ID (0..stagger_window)
        node_hash = hashlib.sha256(
            self._jitter_config.node_id.encode("utf-8")
        ).hexdigest()
        self._jitter_offset = (
            int(node_hash[:8], 16) % (self._jitter_config.stagger_window * 1000)
        ) / 1000.0  # ms precision

    @property
    def jitter_offset(self) -> float:
        """The per-node stagger offset in seconds (0..stagger_window)."""
        return self._jitter_offset

    # ---- Core API (unchanged) ----

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

    # ---- Reconciliation stagger API ----

    def setup_periodic_task(
        self,
        name: str,
        callback: Callable[[], None],
        interval: Optional[float] = None,
    ) -> None:
        """Register a periodic reconciliation task with automatic startup jitter.
        
        The first invocation is delayed by the node's jitter_offset so that
        different nodes in a cluster spread their initial reconciliation across
        the stagger_window. Subsequent invocations enforce the base_interval gap.
        
        Args:
            name: Unique task name (used for dedup and audit records).
            callback: Zero-argument callable to invoke when reconciliation runs.
            interval: Override for JitterConfig.base_interval. Defaults to config.
        """
        self._periodic_tasks[name] = (
            callback,
            interval if interval is not None else self._jitter_config.base_interval,
            self._startup_time + self._jitter_offset,
        )

    def run_periodic_task(self, name: str) -> str:
        """Execute one reconciliation cycle for *name* with stagger enforcement.
        
        Returns an audit action string: "accepted", "deferred", or "rejected".
        """
        if name not in self._periodic_tasks:
            self._append_audit("rejected", f"Unknown periodic task: {name}")
            return "rejected"

        callback, base_interval, first_run_at = self._periodic_tasks[name]
        now = time.time()

        with self._reconcile_lock:
            # --- Startup deferral ---
            if now < first_run_at:
                remaining = first_run_at - now
                self._append_audit(
                    "deferred",
                    f"Startup stagger active — {remaining:.1f}s until first scheduled reconciliation"
                )
                return "deferred"

            # --- Interval enforcement ---
            elapsed = now - self._last_reconcile_time
            if elapsed < base_interval:
                remaining = base_interval - elapsed
                self._append_audit(
                    "deferred",
                    f"Interval guard active — only {elapsed:.1f}s since last reconcile "
                    f"(need {base_interval:.0f}s), next due in {remaining:.1f}s"
                )
                return "deferred"

            # --- Accept ---
            self._last_reconcile_time = now
            self._append_audit("accepted", f"Reconciliation {name} started")

        # Execute outside the lock so concurrent invocations don't deadlock
        try:
            callback()
        except Exception:
            self._append_audit("rejected", f"Reconciliation {name} raised an exception")
            return "rejected"

        return "accepted"

    def _append_audit(self, action: str, reason: str) -> None:
        """Thread-safe audit log append (bounded ring buffer)."""
        entry = ReconciliationAuditEntry(
            timestamp=time.time(),
            node_id=self._jitter_config.node_id,
            action=action,
            reason=reason,
        )
        with self._reconcile_lock:
            self._audit_log.append(entry)

    def get_audit_log(self, limit: Optional[int] = None) -> List[ReconciliationAuditEntry]:
        """Return recent audit entries (newest first). No private data exposed."""
        with self._reconcile_lock:
            entries = list(self._audit_log)
        entries.reverse()
        if limit is not None:
            return entries[:limit]
        return entries

    def clear_audit_log(self) -> None:
        """Clear the audit ring buffer."""
        with self._reconcile_lock:
            self._audit_log.clear()

# 2019-04-25T08:37:12 update
# 2019-06-04T16:40:00 update
# 2019-07-11T12:01:28 update
# 2019-08-02T12:20:21 update
# 2019-08-23T10:38:50 update
# 2019-10-31T13:55:52 update
# 2019-11-04T20:12:32 update
# 2019-12-13T12:22:36 update
# 2020-02-01T10:32:37 update
# 2020-02-26T09:44:38 update
# 2020-03-09T19:00:55 update
# 2020-05-01T18:40:34 update
# 2020-05-12T15:10:31 update
# 2020-06-30T13:24:19 update
# 2020-09-22T16:00:45 update
# 2020-10-20T10:52:48 update
# 2020-10-21T12:18:08 update
# 2020-11-06T12:35:01 update
# 2020-12-09T08:09:33 update
# 2021-01-07T08:20:36 update
# 2021-10-02T15:23:16 update
# 2021-10-06T16:14:57 update
# 2021-10-06T09:27:41 update
# 2021-11-19T08:37:40 update
# 2022-03-01T16:39:54 update
# 2022-05-26T13:43:07 update
# 2022-06-02T10:50:58 update
# 2022-06-14T10:46:48 update
# 2022-07-31T16:44:34 update
# 2022-08-30T18:20:12 update
# 2022-11-04T14:47:03 update
# 2022-12-06T10:36:49 update
# 2022-12-22T13:21:12 update
# 2022-12-26T12:24:50 update
# 2023-03-09T08:09:55 update
# 2023-05-01T10:07:37 update
# 2023-06-08T14:32:15 update
# 2023-07-14T17:24:18 update
# 2023-12-14T08:38:31 update
# 2024-02-20T13:43:58 update
# 2024-03-24T08:52:42 update
# 2024-03-28T15:27:17 update
# 2024-03-29T18:10:33 update
# 2024-04-15T20:18:31 update
# 2024-05-27T13:11:52 update
# 2024-05-27T16:42:56 update
# 2024-06-20T13:03:45 update
# 2024-06-28T12:32:58 update
# 2024-07-10T14:10:16 update
# 2024-07-26T14:18:59 update
# 2024-08-12T08:21:05 update
# 2024-08-21T16:58:40 update
# 2024-09-27T19:54:30 update
# 2024-10-21T13:47:42 update
# 2024-11-11T09:19:27 update
# 2024-12-24T08:23:41 update
# 2025-02-14T10:35:15 update
# 2025-03-31T18:09:40 update
# 2025-06-21T17:32:49 update
# 2025-07-21T16:52:28 update
# 2025-08-20T19:45:16 update
# 2025-11-04T18:54:24 update
# 2025-12-09T20:17:36 update
# 2026-01-12T15:42:32 update
# 2026-01-23T14:41:20 update
# 2026-03-18T14:43:07 update
# 2026-04-13T11:43:19 update
# 2026-05-24T00:00:00 update  -- Added JitterConfig, ReconciliationAuditEntry, periodic tasks, stagger guard
