"""Task Scheduler — Priority-based task queuing and dispatch with external service health gates."""

import asyncio
import heapq
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


class ServiceHealth(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"


class ExternalServiceHealthGate:
    """Health gate that defers scheduling when external dependencies are unavailable.

    Tracks external service health and prevents dispatching tasks that depend on
    unhealthy services. Deferred tasks are stored and retried on a health-recovery
    check interval.
    """

    def __init__(self, check_interval: float = 5.0, max_retry_attempts: int = 10):
        self._service_health: Dict[str, ServiceHealth] = {}
        self._check_interval = check_interval
        self._max_retry_attempts = max_retry_attempts
        self._deferred: Dict[str, List[Dict]] = {}
        self._last_check: Dict[str, float] = {}
        self._recently_recovered: Set[str] = set()

    def register_service(self, service_name: str) -> None:
        """Register a service for health tracking."""
        if service_name not in self._service_health:
            self._service_health[service_name] = ServiceHealth.HEALTHY
            self._deferred[service_name] = []

    def update_health(self, service_name: str, health: ServiceHealth) -> None:
        """Update health status for a service."""
        prev_health = self._service_health.get(service_name, ServiceHealth.HEALTHY)
        self._service_health[service_name] = health
        self._last_check[service_name] = time.time()

        if prev_health in (ServiceHealth.DEGRADED, ServiceHealth.UNREACHABLE) and health == ServiceHealth.HEALTHY:
            self._recently_recovered.add(service_name)

    def get_health(self, service_name: str) -> ServiceHealth:
        """Get current health status for a service."""
        return self._service_health.get(service_name, ServiceHealth.HEALTHY)

    def can_dispatch(self, service_name: str) -> bool:
        """Check whether tasks for this service can be dispatched now."""
        health = self.get_health(service_name)
        return health == ServiceHealth.HEALTHY

    def defer_task(self, task: Dict, service_name: str) -> bool:
        """Defer a task when its required service is unavailable."""
        if service_name not in self._deferred:
            self._deferred[service_name] = []
        retries = task.get("_health_retries", 0)
        if retries >= self._max_retry_attempts:
            logger.warning(
                "Task %s exceeded max health gate retries (%d) for service %s",
                task.get("id", "unknown"), self._max_retry_attempts, service_name
            )
            return False
        task["_health_retries"] = retries + 1
        task["_deferred_at"] = time.time()
        task["_deferred_service"] = service_name
        self._deferred[service_name].append(task)
        logger.info("Deferred task %s for service %s (attempt %d)",
                     task.get("id", "unknown"), service_name, retries + 1)
        return True

    def recover_deferred(self, service_name: str) -> List[Dict]:
        """Retrieve all deferred tasks for a recently recovered service."""
        if service_name in self._recently_recovered:
            self._recently_recovered.discard(service_name)
            tasks = list(self._deferred.get(service_name, []))
            self._deferred[service_name] = []
            if tasks:
                logger.info("Recovered %d deferred tasks for service %s", len(tasks), service_name)
            return tasks
        return []

    def get_deferred_count(self, service_name: Optional[str] = None) -> int:
        """Get count of deferred tasks, optionally filtered by service."""
        if service_name:
            return len(self._deferred.get(service_name, []))
        return sum(len(tasks) for tasks in self._deferred.values())

    def should_recheck(self, service_name: str) -> bool:
        """Check whether enough time has passed to recheck service health."""
        last = self._last_check.get(service_name, 0.0)
        return (time.time() - last) >= self._check_interval


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
        self._health_gate = ExternalServiceHealthGate()

    @property
    def health_gate(self) -> ExternalServiceHealthGate:
        """Access the health gate for external service monitoring."""
        return self._health_gate

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0,
                 required_service: Optional[str] = None) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["_required_service"] = required_service

        if required_service and not self._health_gate.can_dispatch(required_service):
            self._health_gate.register_service(required_service)
            deferred = self._health_gate.defer_task(task, required_service)
            if not deferred:
                logger.error("Failed to defer task %s for service %s", task_id, required_service)
            return task_id

        self._scheduled[task_id] = time.time() + delay
        return task_id

    async def dequeue(self, queue: str = "default", timeout: float = 1.0) -> Optional[Dict]:
        now = time.time()

        expired = [tid for tid, t in self._scheduled.items() if t <= now]
        for tid in expired:
            task = self._scheduled.pop(tid)
            if task:
                required_service = task.get("_required_service")
                if required_service and not self._health_gate.can_dispatch(required_service):
                    self._health_gate.defer_task(task, required_service)
                    continue
                self.enqueue(task, queue)

        if queue in self._queues and len(self._queues[queue]) > 0:
            task = self._queues[queue].pop()
            if task:
                required_service = task.get("_required_service")
                if required_service and not self._health_gate.can_dispatch(required_service):
                    self._health_gate.defer_task(task, required_service)
                    return None
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
