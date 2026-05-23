"""Retry Tracker — Attempt-scoped retry counters for parallel branch retries."""

import threading
from typing import Dict, Optional


class RetryTracker:
    """Provides attempt-scoped retry counters.

    In a parallel branch execution, each branch attempt needs its own
    isolated retry counter. This prevents one branch's retries from
    consuming another branch's retry budget.

    Key behaviors:
    - Each (task_id, attempt_id) pair gets its own isolated counter.
    - Counter is initialized at 0 when first accessed.
    - get_retry_count() returns the current attempt number.
    - increment() advances the counter and returns the new value.
    - reset() clears counters for a given task_id (all its attempts).
    """

    def __init__(self, max_retries: int = 3):
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._counters: Dict[tuple, int] = {}

    @property
    def max_retries(self) -> int:
        return self._max_retries

    def get_retry_count(self, task_id: str, attempt_id: str = "default") -> int:
        with self._lock:
            return self._counters.get((task_id, attempt_id), 0)

    def increment(self, task_id: str, attempt_id: str = "default") -> int:
        with self._lock:
            key = (task_id, attempt_id)
            self._counters[key] = self._counters.get(key, 0) + 1
            return self._counters[key]

    def can_retry(self, task_id: str, attempt_id: str = "default") -> bool:
        with self._lock:
            key = (task_id, attempt_id)
            count = self._counters.get(key, 0)
            return count < self._max_retries

    def remaining(self, task_id: str, attempt_id: str = "default") -> int:
        with self._lock:
            key = (task_id, attempt_id)
            count = self._counters.get(key, 0)
            return max(0, self._max_retries - count)

    def reset(self, task_id: str) -> None:
        with self._lock:
            keys_to_delete = [k for k in self._counters if k[0] == task_id]
            for k in keys_to_delete:
                del self._counters[k]

    def reset_attempt(self, task_id: str, attempt_id: str = "default") -> None:
        with self._lock:
            self._counters.pop((task_id, attempt_id), None)
