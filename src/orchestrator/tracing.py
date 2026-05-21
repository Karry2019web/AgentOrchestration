"""Bounded trace aggregation with server-side memory enforcement."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from threading import RLock
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


class AggState(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


TERMINAL = frozenset({AggState.COMPLETED, AggState.REJECTED, AggState.CANCELLED})


class AggError(RuntimeError):
    """Base for trace aggregation failures."""


class MemoryExceeded(AggError):
    """Trace span would exceed the memory budget."""


class ClosedAggregation(AggError):
    """Trying to modify a terminal aggregation."""


@dataclass(frozen=True)
class Span:
    id: str
    operation: str
    wall_ms: float
    tags: Dict[str, Any] = field(default_factory=dict)

    def byte_size(self) -> int:
        """Approximate in-memory size of this span."""
        size = len(self.id) + len(self.operation) + 8  # 8 for wall_ms float
        size += sum(len(k) + len(str(v)) for k, v in self.tags.items())
        return size


@dataclass(frozen=True)
class Outcome:
    run_id: str
    state: AggState
    reason: str
    bytes_used: int
    span_count: int
    timestamp: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "state": self.state.value,
            "reason": self.reason,
            "bytes_used": self.bytes_used,
            "span_count": self.span_count,
            "timestamp": self.timestamp,
        }


Clock = Callable[[], float]


class TraceMemoryGuard:
    """Enforces a per-run memory budget on trace span aggregation.

    Once the budget is exceeded the run is marked ``REJECTED`` and no further
    spans are accepted.  Terminal runs (``COMPLETED``, ``REJECTED``,
    ``CANCELLED``) reject all subsequent writes with ``ClosedAggregation``.
    """

    def __init__(self, max_bytes: int, clock: Clock = time.time):
        self._max = max_bytes
        self._clock = clock
        self._lock = RLock()
        # run_id -> (state, bytes_used, spans)
        self._runs: Dict[str, Tuple[AggState, int, List[Span]]] = {}
        self._outcomes: Dict[str, Outcome] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def accept(self, run_id: str, span: Span) -> None:
        """Try to record *span* under *run_id*.

        Raises ``MemoryExceeded`` or ``ClosedAggregation`` on failure.
        """
        with self._lock:
            state, used, spans = self._runs.get(run_id, (AggState.ACTIVE, 0, []))

            if state in TERMINAL:
                raise ClosedAggregation(
                    f"run '{run_id}' is {state.value}, no longer accepts spans"
                )

            added = span.byte_size()
            if used + added > self._max:
                self._runs[run_id] = (AggState.REJECTED, used, spans)
                self._outcomes[run_id] = Outcome(
                    run_id=run_id,
                    state=AggState.REJECTED,
                    reason="memory_limit_exceeded",
                    bytes_used=used,
                    span_count=len(spans),
                    timestamp=self._clock(),
                )
                raise MemoryExceeded(
                    f"run '{run_id}' would exceed {self._max} byte limit "
                    f"({used}+{added}>{self._max})"
                )

            spans.append(span)
            self._runs[run_id] = (state, used + added, spans)

    def complete(self, run_id: str, reason: str = "completed") -> Outcome:
        """Mark a run as completed and return its outcome."""
        with self._lock:
            state, used, spans = self._runs.get(run_id, (AggState.ACTIVE, 0, []))
            if state in TERMINAL:
                raise ClosedAggregation(
                    f"run '{run_id}' is already {state.value}"
                )
            self._runs[run_id] = (AggState.COMPLETED, used, spans)
            outcome = Outcome(
                run_id=run_id,
                state=AggState.COMPLETED,
                reason=reason,
                bytes_used=used,
                span_count=len(spans),
                timestamp=self._clock(),
            )
            self._outcomes[run_id] = outcome
            return outcome

    def cancel(self, run_id: str, reason: str = "cancelled") -> Outcome:
        with self._lock:
            state, used, spans = self._runs.get(run_id, (AggState.ACTIVE, 0, []))
            if state in TERMINAL:
                raise ClosedAggregation(
                    f"run '{run_id}' is already {state.value}"
                )
            self._runs[run_id] = (AggState.CANCELLED, used, spans)
            outcome = Outcome(
                run_id=run_id,
                state=AggState.CANCELLED,
                reason=reason,
                bytes_used=used,
                span_count=len(spans),
                timestamp=self._clock(),
            )
            self._outcomes[run_id] = outcome
            return outcome

    def snapshot(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Return a summary dict for *run_id* or ``None`` if unknown."""
        with self._lock:
            entry = self._runs.get(run_id)
            if entry is None:
                return None
            state, used, spans = entry
            return {
                "run_id": run_id,
                "state": state.value,
                "spans": [s.id for s in spans],
                "span_count": len(spans),
                "bytes_used": used,
                "byte_limit": self._max,
            }

    def outcome(self, run_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            o = self._outcomes.get(run_id)
            return o.to_dict() if o else None

    def reset(self) -> None:
        with self._lock:
            self._runs.clear()
            self._outcomes.clear()

    @property
    def byte_limit(self) -> int:
        return self._max
