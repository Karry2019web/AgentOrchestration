"""Reducer Error Store — Persists reducer errors separately from primary event log."""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4


class ErrorSeverity(Enum):
    """Severity levels for reducer errors."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ReducerError:
    """A single reducer error record with context and metadata."""
    
    def __init__(
        self,
        error_id: str,
        run_id: str,
        severity: ErrorSeverity,
        message: str,
        event_payload: Optional[Dict[str, Any]] = None,
        reducer_name: Optional[str] = None,
    ):
        self.error_id = error_id
        self.run_id = run_id
        self.severity = severity
        self.message = message
        self.event_payload = event_payload or {}
        self.reducer_name = reducer_name or "unknown"
        self.timestamp = datetime.now(timezone.utc)
        self.resolved = False
        self.resolved_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_id": self.error_id,
            "run_id": self.run_id,
            "severity": self.severity.value,
            "message": self.message,
            "event_payload": self.event_payload,
            "reducer_name": self.reducer_name,
            "timestamp": self.timestamp.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
        }


class ReducerErrorStore:
    """Separate store for reducer errors, preserving event processing diagnostics."""
    
    def __init__(self):
        self._errors: Dict[str, ReducerError] = {}
    
    def record_error(
        self,
        run_id: str,
        message: str,
        severity: ErrorSeverity = ErrorSeverity.MEDIUM,
        event_payload: Optional[Dict[str, Any]] = None,
        reducer_name: Optional[str] = None,
    ) -> str:
        """Persist a reducer error with run context, severity, and event payload."""
        error_id = str(uuid4())
        error = ReducerError(
            error_id=error_id,
            run_id=run_id,
            severity=severity,
            message=message,
            event_payload=event_payload,
            reducer_name=reducer_name,
        )
        self._errors[error_id] = error
        return error_id
    
    def get_run_errors(self, run_id: str) -> List[Dict[str, Any]]:
        """Retrieve all errors for a specific run (separate from event log)."""
        return [
            error.to_dict()
            for error in self._errors.values()
            if error.run_id == run_id
        ]
    
    def get_all_errors(
        self,
        severity: Optional[ErrorSeverity] = None,
        include_resolved: bool = False,
    ) -> List[Dict[str, Any]]:
        """Global diagnostic view, filterable by severity."""
        result = []
        for error in self._errors.values():
            if not include_resolved and error.resolved:
                continue
            if severity and error.severity != severity:
                continue
            result.append(error.to_dict())
        return result
    
    def get_error_counts(self) -> Dict[str, int]:
        """Aggregate diagnostic counts by severity."""
        counts: Dict[str, int] = {}
        for error in self._errors.values():
            if not error.resolved:
                sev = error.severity.value
                counts[sev] = counts.get(sev, 0) + 1
        return counts
    
    def resolve_error(self, error_id: str) -> bool:
        """Mark a reducer error as resolved."""
        error = self._errors.get(error_id)
        if not error:
            return False
        error.resolved = True
        error.resolved_at = datetime.now(timezone.utc)
        return True
    
    def clear_run_errors(self, run_id: str) -> int:
        """Remove all errors for a specific run (lifecycle management)."""
        to_remove = [
            eid for eid, err in self._errors.items()
            if err.run_id == run_id
        ]
        for eid in to_remove:
            del self._errors[eid]
        return len(to_remove)
