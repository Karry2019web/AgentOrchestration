"""Trace Aggregator — Collects and limits trace data with memory enforcement."""

import time
import logging
from threading import Lock
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default memory limit in bytes (4 MB)
DEFAULT_MEMORY_LIMIT_BYTES = 4 * 1024 * 1024


class TraceMemoryLimitError(Exception):
    """Raised when trace aggregation exceeds the configured memory limit."""
    pass


class TraceEntry:
    """A single trace entry with metadata."""

    def __init__(self, trace_id: str, agent_id: str, event: str, payload: Optional[Dict] = None):
        self.trace_id = trace_id
        self.agent_id = agent_id
        self.event = event
        self.payload = payload or {}
        self.timestamp = time.time()

    def size_bytes(self) -> int:
        """Estimate the memory footprint of this entry."""
        base = 64
        base += len(self.trace_id) + len(self.agent_id) + len(self.event)
        for k, v in self.payload.items():
            base += len(str(k)) + len(str(v))
        return base

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "event": self.event,
            "payload": dict(self.payload),
            "timestamp": self.timestamp,
        }


class TraceAggregator:
    """Aggregates trace events with a configurable memory limit.

    When the total estimated size of buffered trace entries exceeds
    ``memory_limit_bytes``, new entries are rejected with a
    ``TraceMemoryLimitError``. This prevents unbounded memory growth
    during trace runtime operations.
    """

    def __init__(self, memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES):
        self._lock = Lock()
        self._entries: List[TraceEntry] = []
        self._current_size = 0
        self._memory_limit = memory_limit_bytes
        self._rejected_count = 0
        self._total_entries = 0

    @property
    def memory_limit_bytes(self) -> int:
        return self._memory_limit

    @property
    def current_size_bytes(self) -> int:
        with self._lock:
            return self._current_size

    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._entries)

    @property
    def rejected_count(self) -> int:
        with self._lock:
            return self._rejected_count

    def record(self, trace_id: str, agent_id: str, event: str, payload: Optional[Dict] = None) -> bool:
        """Record a trace entry. Returns True if accepted, False if rejected due to memory limit."""
        entry = TraceEntry(trace_id, agent_id, event, payload)
        entry_size = entry.size_bytes()

        with self._lock:
            if self._current_size + entry_size > self._memory_limit:
                self._rejected_count += 1
                logger.warning(
                    "Trace entry rejected: memory limit %d bytes reached (current=%d, new=%d)",
                    self._memory_limit, self._current_size, entry_size,
                )
                return False

            self._entries.append(entry)
            self._current_size += entry_size
            self._total_entries += 1
            return True

    def flush(self) -> List[Dict[str, Any]]:
        """Return all buffered entries and clear the buffer."""
        with self._lock:
            entries = [e.to_dict() for e in self._entries]
            self._entries.clear()
            self._current_size = 0
        return entries

    def snapshot(self) -> Dict[str, Any]:
        """Return current state without clearing."""
        with self._lock:
            return {
                "entry_count": len(self._entries),
                "current_size_bytes": self._current_size,
                "memory_limit_bytes": self._memory_limit,
                "rejected_count": self._rejected_count,
                "total_entries": self._total_entries,
                "usage_pct": round(
                    (self._current_size / self._memory_limit) * 100, 2
                ) if self._memory_limit > 0 else 0,
            }

    def has_capacity(self) -> bool:
        """Check if the aggregator can accept more entries."""
        with self._lock:
            return self._current_size < self._memory_limit

# 2026-05-23T09:50:00 update
