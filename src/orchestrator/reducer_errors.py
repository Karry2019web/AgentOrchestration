"""Reducer error store — persists reducer errors separately for event processing diagnostics."""

import time
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from threading import Lock


class ReducerErrorSeverity(Enum):
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ReducerError:
    def __init__(self, run_id: str, reducer_name: str, error_type: str,
                 message: str, severity: ReducerErrorSeverity = ReducerErrorSeverity.ERROR,
                 event_payload: Optional[Dict] = None, run_version: int = 0):
        self.error_id = str(uuid4())
        self.run_id = run_id
        self.reducer_name = reducer_name
        self.error_type = error_type
        self.message = message
        self.severity = severity
        self.event_payload = event_payload
        self.run_version = run_version
        self.timestamp = time.time()
        self.resolved = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_id": self.error_id,
            "run_id": self.run_id,
            "reducer_name": self.reducer_name,
            "error_type": self.error_type,
            "message": self.message,
            "severity": self.severity.value,
            "event_payload": self.event_payload,
            "run_version": self.run_version,
            "timestamp": self.timestamp,
            "resolved": self.resolved,
        }


class ReducerErrorStore:
    def __init__(self):
        self._lock = Lock()
        self._errors: Dict[str, ReducerError] = {}
        self._run_errors: Dict[str, List[str]] = {}

    def record_error(self, run_id: str, reducer_name: str, error_type: str,
                     message: str, severity: ReducerErrorSeverity = ReducerErrorSeverity.ERROR,
                     event_payload: Optional[Dict] = None, run_version: int = 0) -> str:
        error = ReducerError(run_id, reducer_name, error_type, message, severity,
                             event_payload, run_version)
        with self._lock:
            self._errors[error.error_id] = error
            if run_id not in self._run_errors:
                self._run_errors[run_id] = []
            self._run_errors[run_id].append(error.error_id)
        return error.error_id

    def get_run_errors(self, run_id: str) -> List[Dict]:
        with self._lock:
            return [self._errors[eid].to_dict() for eid in self._run_errors.get(run_id, []) if eid in self._errors]

    def get_all_errors(self, severity: Optional[ReducerErrorSeverity] = None) -> List[Dict]:
        with self._lock:
            results = [e.to_dict() for e in self._errors.values()]
            if severity:
                results = [r for r in results if r["severity"] == severity.value]
            return sorted(results, key=lambda x: x["timestamp"], reverse=True)

    def get_error_counts(self) -> Dict[str, int]:
        with self._lock:
            counts = {"total": len(self._errors)}
            for e in self._errors.values():
                sev = e.severity.value
                counts[sev] = counts.get(sev, 0) + 1
            return counts

    def resolve_error(self, error_id: str) -> bool:
        with self._lock:
            error = self._errors.get(error_id)
            if not error:
                return False
            error.resolved = True
            return True

    def clear_run_errors(self, run_id: str) -> int:
        with self._lock:
            error_ids = self._run_errors.pop(run_id, [])
            count = 0
            for eid in error_ids:
                if eid in self._errors:
                    del self._errors[eid]
                    count += 1
            return count


reducer_error_store = ReducerErrorStore()
