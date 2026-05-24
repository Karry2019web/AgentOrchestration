"""Reducer Error Store — Persist reducer errors separately for event processing diagnostics."""

import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Severity levels for reducer errors."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReducerErrorRecord:
    """A single reducer error with full diagnostic context."""

    def __init__(
        self,
        run_id: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        event_payload: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
    ):
        self.id = str(uuid4())
        self.run_id = run_id
        self.message = message
        self.severity = severity
        self.event_payload = event_payload or {}
        self.context = context or {}
        self.timestamp = time.time()
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.resolved = False
        self.resolved_at: Optional[str] = None
        self.attempt: int = 0
        self.revision: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "message": self.message,
            "severity": self.severity.value,
            "event_payload": self.event_payload,
            "context": self.context,
            "timestamp": self.timestamp,
            "created_at": self.created_at,
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
            "attempt": self.attempt,
            "revision": self.revision,
        }


class ReducerErrorStore:
    """Persists reducer errors in a separate store, guarding against stale/duplicate/dangerous transitions.

    Each error carries attempt, revision, and lifecycle metadata so that
    the reducer or dispatch transition can validate whether an incoming
    transition has already been processed (duplicate), arrived out of order
    (stale), or violates lifecycle state (policy-violating).
    """

    def __init__(self, max_errors_per_run: int = 1000):
        self._errors: Dict[str, ReducerErrorRecord] = {}  # id -> record
        self._run_errors: Dict[str, List[str]] = defaultdict(list)  # run_id -> [error_ids]
        self._run_attempts: Dict[str, int] = defaultdict(int)  # run_id -> latest attempt
        self._run_revisions: Dict[str, int] = defaultdict(int)  # run_id -> latest revision
        self._run_lifecycle: Dict[str, str] = {}  # run_id -> lifecycle state
        self._max_errors_per_run = max_errors_per_run

    # ---- Guard / Validation ----

    def _validate_transition(self, run_id: str, attempt: int, revision: int, lifecycle: str) -> Optional[str]:
        """Validate whether a transition is acceptable.

        Returns None if the transition is valid, or an error message string if rejected.
        """
        # Stale transition: attempt or revision went backwards
        current_attempt = self._run_attempts.get(run_id, 0)
        if attempt < current_attempt:
            return (
                f"Stale transition rejected: attempt {attempt} < "
                f"current attempt {current_attempt} for run {run_id}"
            )

        current_revision = self._run_revisions.get(run_id, 0)
        if attempt == current_attempt and revision < current_revision:
            return (
                f"Stale transition rejected: revision {revision} < "
                f"current revision {current_revision} for run {run_id} "
                f"(same attempt {attempt})"
            )

        # Duplicate transition: same attempt and revision already processed
        if attempt == current_attempt and revision == current_revision:
            return (
                f"Duplicate transition rejected: attempt {attempt}, "
                f"revision {revision} already processed for run {run_id}"
            )

        # Lifecycle state violation: dangerous state transitions
        valid_lifecycles = {"pending", "running", "paused", "completed", "failed", "cancelled"}
        if lifecycle not in valid_lifecycles:
            return (
                f"Invalid lifecycle state '{lifecycle}' for run {run_id}. "
                f"Must be one of: {', '.join(sorted(valid_lifecycles))}"
            )

        current_lifecycle = self._run_lifecycle.get(run_id, "pending")

        # Guard: cannot transition from completed/failed to running without new attempt
        if current_lifecycle in ("completed", "failed") and lifecycle == "running":
            if attempt <= current_attempt:
                return (
                    f"Lifecycle violation: cannot transition from '{current_lifecycle}' "
                    f"to '{lifecycle}' without a new attempt (attempt {attempt} <= "
                    f"current attempt {current_attempt}) for run {run_id}"
                )

        # Guard: cannot transition from cancelled
        if current_lifecycle == "cancelled" and lifecycle != "cancelled":
            return (
                f"Lifecycle violation: cannot transition from 'cancelled' "
                f"to '{lifecycle}' for run {run_id}"
            )

        return None  # Valid transition

    # ---- Core API ----

    def record_error(
        self,
        run_id: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.ERROR,
        event_payload: Optional[Dict[str, Any]] = None,
        context: Optional[Dict[str, Any]] = None,
        attempt: int = 0,
        revision: int = 0,
        lifecycle: str = "pending",
    ) -> ReducerErrorRecord:
        """Record a reducer error with guard validation.

        Returns the error record if the transition passes guards and the
        error is recorded, raises ValueError if the transition is rejected.
        """
        # Validate the transition before recording
        rejection = self._validate_transition(run_id, attempt, revision, lifecycle)
        if rejection:
            # Record the rejection as an error for diagnostics
            error = ReducerErrorRecord(
                run_id=run_id,
                message=rejection,
                severity=ErrorSeverity.WARNING,
                event_payload=event_payload,
                context={**(context or {}), "rejection": True, "attempt": attempt, "revision": revision},
            )
            self._persist_error(error, run_id)
            logger.warning(f"Reducer transition rejected: {rejection}")
            raise ValueError(rejection)

        error = ReducerErrorRecord(
            run_id=run_id,
            message=message,
            severity=severity,
            event_payload=event_payload,
            context=context,
        )
        error.attempt = attempt
        error.revision = revision

        self._persist_error(error, run_id)

        # Update tracking state
        if attempt > self._run_attempts.get(run_id, 0):
            self._run_attempts[run_id] = attempt
        if revision > self._run_revisions.get(run_id, 0) and attempt >= self._run_attempts.get(run_id, 0):
            self._run_revisions[run_id] = revision
        self._run_lifecycle[run_id] = lifecycle

        logger.info(
            f"Reducer error recorded: run={run_id} "
            f"severity={severity.value} attempt={attempt} "
            f"revision={revision} lifecycle={lifecycle}"
        )
        return error

    def _persist_error(self, error: ReducerErrorRecord, run_id: str) -> None:
        """Store an error record, enforcing per-run capacity."""
        run_error_ids = self._run_errors.get(run_id, [])
        if len(run_error_ids) >= self._max_errors_per_run:
            logger.warning(
                f"Run {run_id} has reached max errors ({self._max_errors_per_run}). "
                f"Dropping oldest error for this run."
            )
            oldest_id = run_error_ids.pop(0)
            self._errors.pop(oldest_id, None)

        self._errors[error.id] = error
        self._run_errors[run_id].append(error.id)

    def get_run_errors(self, run_id: str) -> List[ReducerErrorRecord]:
        """Retrieve all errors for a specific run (separate from primary event log)."""
        return [self._errors[eid] for eid in self._run_errors.get(run_id, []) if eid in self._errors]

    def get_all_errors(self, severity: Optional[str] = None) -> List[ReducerErrorRecord]:
        """Global diagnostic view, optionally filterable by severity."""
        if severity:
            try:
                sev = ErrorSeverity(severity.lower())
                return [e for e in self._errors.values() if e.severity == sev]
            except ValueError:
                logger.warning(f"Invalid severity filter: {severity}")
                return []
        return list(self._errors.values())

    def get_error_counts(self) -> Dict[str, int]:
        """Aggregate diagnostic counts by severity and total."""
        counts: Dict[str, int] = {"total": 0}
        for error in self._errors.values():
            sev = error.severity.value
            counts[sev] = counts.get(sev, 0) + 1
            counts["total"] += 1
            if error.resolved:
                counts["resolved"] = counts.get("resolved", 0) + 1
        return counts

    def resolve_error(self, error_id: str) -> bool:
        """Mark a specific error as resolved."""
        error = self._errors.get(error_id)
        if error and not error.resolved:
            error.resolved = True
            error.resolved_at = datetime.now(timezone.utc).isoformat()
            logger.info(f"Reducer error {error_id} marked as resolved")
            return True
        return False

    def clear_run_errors(self, run_id: str) -> int:
        """Clear all errors for a specific run. Returns count of removed errors."""
        error_ids = self._run_errors.pop(run_id, [])
        count = 0
        for eid in error_ids:
            if eid in self._errors:
                del self._errors[eid]
                count += 1
        self._run_attempts.pop(run_id, None)
        self._run_revisions.pop(run_id, None)
        self._run_lifecycle.pop(run_id, None)
        logger.info(f"Cleared {count} errors for run {run_id}")
        return count

    def clear_all(self) -> int:
        """Clear all stored errors and tracking state. Returns count."""
        count = len(self._errors)
        self._errors.clear()
        self._run_errors.clear()
        self._run_attempts.clear()
        self._run_revisions.clear()
        self._run_lifecycle.clear()
        logger.info(f"Cleared all {count} errors from store")
        return count

    @property
    def error_count(self) -> int:
        return len(self._errors)

    @property
    def run_count(self) -> int:
        return len(self._run_errors)


# Module-level singleton
reducer_error_store = ReducerErrorStore()
