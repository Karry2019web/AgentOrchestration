"""Task Scheduler — Priority-based task queuing and dispatch.

Supports bounded retries with exponential backoff + jitter
and state-machine guards for idempotent failure recovery.
"""

import asyncio
import enum
import heapq
import random
import time
from typing import Any, Dict, Optional, Set
from uuid import uuid4


# --- Retry constants ---
DEFAULT_MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0   # seconds
MAX_RETRY_DELAY = 60.0   # seconds
JITTER_FACTOR = 0.5      # ±50% jitter


class TaskState(enum.Enum):
    """Durable state-machine for task lifecycle."""
    PENDING = "pending"
    ENQUEUED = "enqueued"
    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Valid state transitions for the state-machine guard
VALID_TRANSITIONS = {
    TaskState.PENDING: {TaskState.ENQUEUED, TaskState.CANCELLED},
    TaskState.ENQUEUED: {TaskState.IN_FLIGHT, TaskState.CANCELLED},
    TaskState.IN_FLIGHT: {TaskState.COMPLETED, TaskState.FAILED, TaskState.ENQUEUED},
    TaskState.COMPLETED: set(),
    TaskState.FAILED: {TaskState.ENQUEUED},
    TaskState.CANCELLED: set(),
}


def _retry_delay(attempt: int) -> float:
    """Compute exponential backoff delay with jitter.

    delay = min(BASE * 2^attempt, MAX) * uniform(1-JITTER, 1+JITTER)
    """
    base = BASE_RETRY_DELAY * (2 ** attempt)
    capped = min(base, MAX_RETRY_DELAY)
    jitter = 1.0 + JITTER_FACTOR * (2.0 * random.random() - 1.0)
    return round(capped * jitter, 3)


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
        self._max_retries = DEFAULT_MAX_RETRIES
        # Durable state tracking — prevents duplicate/out-of-order processing
        self._states: Dict[str, TaskState] = {}
        self._terminal_states: Dict[str, TaskState] = {}  # immutable record

    def _transition(self, task_id: str, new_state: TaskState) -> bool:
        """Apply state-machine guard before allowing transition.

        Returns True if the transition is valid and applied.
        """
        # Terminal states are immutable
        if task_id in self._terminal_states:
            return False

        current = self._states.get(task_id, TaskState.PENDING)

        if new_state not in VALID_TRANSITIONS.get(current, set()):
            return False

        self._states[task_id] = new_state

        # Persist terminal outcome before emitting side effects
        if new_state in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            self._terminal_states[task_id] = new_state
            del self._states[task_id]

        return True

    def enqueue(self, task: Dict, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        task["enqueued_at"] = time.time()
        task["retries"] = 0
        task["max_retries"] = self._max_retries

        if not self._transition(task_id, TaskState.ENQUEUED):
            return ""

        if queue not in self._queues:
            self._queues[queue] = PriorityQueue()
        self._queues[queue].push(task, priority)
        return task_id

    def schedule(self, task: Dict, delay: float, queue: str = "default", priority: int = 0) -> str:
        task_id = str(uuid4())
        task["id"] = task_id
        self._scheduled[task_id] = time.time() + delay
        self._transition(task_id, TaskState.ENQUEUED)
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
                if self._transition(task_id, TaskState.IN_FLIGHT):
                    self._in_flight[task_id] = task
                    return task
        return None

    def complete(self, task_id: str) -> bool:
        if not self._transition(task_id, TaskState.COMPLETED):
            return False
        self._in_flight.pop(task_id, None)
        return True

    def fail(self, task_id: str, queue: str = "default") -> bool:
        task = self._in_flight.pop(task_id, None)
        if not task:
            return False

        task["retries"] += 1
        if task["retries"] < task.get("max_retries", self._max_retries):
            if not self._transition(task_id, TaskState.ENQUEUED):
                return False
            # Apply exponential backoff with jitter for retry
            delay = _retry_delay(task["retries"])
            task["retry_at"] = time.time() + delay
            self._scheduled[task_id] = time.time() + delay
            self.enqueue(task, queue, priority=task.get("priority", 0))
            return True
        else:
            self._transition(task_id, TaskState.FAILED)
            return False

    def cancel(self, task_id: str) -> bool:
        """Cancel a task regardless of its current state."""
        self._in_flight.pop(task_id, None)
        return self._transition(task_id, TaskState.CANCELLED)

    def get_state(self, task_id: str) -> Optional[TaskState]:
        if task_id in self._terminal_states:
            return self._terminal_states[task_id]
        return self._states.get(task_id, TaskState.PENDING)

    def is_terminal(self, task_id: str) -> bool:
        return task_id in self._terminal_states

