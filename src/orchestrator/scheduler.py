"""Task Scheduler — Priority-based task queuing and dispatch."""

import asyncio
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
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


@dataclass
class ServiceHealthEntry:
    """Record of an external service health check decision."""
    service_name: str
    healthy: bool
    reason: str
    timestamp: float


class ExternalServiceHealthGate:
    """Health gate that defers scheduler operations when external services are down.

    Tracks known external service dependencies and provides an atomic
    precondition check before enqueue/schedule operations commit state.
    """

    def __init__(self, max_audit_entries: int = 256):
        self._max_audit_entries = max_audit_entries
        self._unhealthy_services: Set[str] = set()
        self._audit_log: List[ServiceHealthEntry] = []
        self._health_checks: Dict[str, float] = {}

    def mark_unhealthy(self, service_name: str, reason: str) -> None:
        """Mark an external service as unavailable."""
        self._unhealthy_services.add(service_name)
        self._health_checks[service_name] = time.time()
        self._append_audit(service_name, healthy=False, reason=reason)

    def mark_healthy(self, service_name: str, reason: str = "recovered") -> None:
        """Mark an external service as available again."""
        self._unhealthy_services.discard(service_name)
        self._health_checks[service_name] = time.time()
        self._append_audit(service_name, healthy=True, reason=reason)

    def is_healthy(self, service_name: str) -> bool:
        """Check if a given external service is currently healthy."""
        return service_name not in self._unhealthy_services

    def is_gate_open(self) -> bool:
        """Returns True if all external dependencies are healthy (gate is open)."""
        return len(self._unhealthy_services) == 0

    def gate_status(self) -> Dict[str, bool]:
        """Returns a snapshot of all known service health statuses."""
        return {svc: svc not in self._unhealthy_services
                for svc in list(self._unhealthy_services) | set(self._health_checks.keys())}

    def get_unhealthy_services(self) -> List[str]:
        """Returns the names of currently unhealthy external services."""
        return sorted(self._unhealthy_services)

    def get_audit_log(self, limit: int = 20) -> List[ServiceHealthEntry]:
        """Returns the most recent audit entries, newest first."""
        return list(reversed(self._audit_log[-limit:]))

    def clear(self) -> None:
        """Reset all health state. Used in tests and after full recovery."""
        self._unhealthy_services.clear()
        self._audit_log.clear()
        self._health_checks.clear()

    def _append_audit(self, service_name: str, healthy: bool, reason: str) -> None:
        entry = ServiceHealthEntry(
            service_name=service_name,
            healthy=healthy,
            reason=reason,
            timestamp=time.time(),
        )
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit_entries:
            self._audit_log = self._audit_log[-self._max_audit_entries:]


@dataclass
class DeferralEntry:
    """Record of a deferred scheduler operation."""
    task_type: str
    task_id: str
    reason: str
    unhealthy_services: List[str]
    timestamp: float


class TaskScheduler:
    def __init__(self, health_gate: Optional[ExternalServiceHealthGate] = None):
        self._queues: Dict[str, PriorityQueue] = {}
        self._scheduled: Dict[str, float] = {}
        self._in_flight: Dict[str, Dict] = {}
        self._max_retries = 3
        self._health_gate = health_gate or ExternalServiceHealthGate()
        self._deferral_log: List[DeferralEntry] = []
        self._max_deferral_entries = 256

    @property
    def health_gate(self) -> ExternalServiceHealthGate:
        return self._health_gate

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> Optional[str]:
        if not self._health_gate.is_gate_open():
            unhealthy = self._health_gate.get_unhealthy_services()
            task_id = str(uuid4())
            task["id"] = task_id
            entry = DeferralEntry(
                task_type=task.get("type", "unknown"),
                task_id=task_id,
                reason="external_service_down",
                unhealthy_services=unhealthy,
                timestamp=time.time(),
            )
            self._deferral_log.append(entry)
            if len(self._deferral_log) > self._max_deferral_entries:
                self._deferral_log = self._deferral_log[-self._max_deferral_entries:]
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
        if not self._health_gate.is_gate_open():
            unhealthy = self._health_gate.get_unhealthy_services()
            task_id = str(uuid4())
            task["id"] = task_id
            entry = DeferralEntry(
                task_type=task.get("type", "unknown"),
                task_id=task_id,
                reason="external_service_down",
                unhealthy_services=unhealthy,
                timestamp=time.time(),
            )
            self._deferral_log.append(entry)
            if len(self._deferral_log) > self._max_deferral_entries:
                self._deferral_log = self._deferral_log[-self._max_deferral_entries:]
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

    def get_deferral_log(self, limit: int = 20) -> List[DeferralEntry]:
        return list(reversed(self._deferral_log[-limit:]))
