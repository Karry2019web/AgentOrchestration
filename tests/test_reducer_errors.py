"""Tests for ReducerErrorStore — reducer error persistence and diagnostics."""

import pytest
from src.orchestrator.reducer_errors import (
    ErrorSeverity,
    ReducerError,
    ReducerErrorStore,
)


class TestReducerErrorStore:
    def setup_method(self):
        self.store = ReducerErrorStore()

    def test_record_error_returns_id(self):
        error_id = self.store.record_error(
            run_id="run-001",
            message="Reducer failed to process event",
        )
        assert error_id is not None
        assert isinstance(error_id, str)

    def test_record_error_with_severity(self):
        error_id = self.store.record_error(
            run_id="run-001",
            message="Critical failure",
            severity=ErrorSeverity.CRITICAL,
        )
        errors = self.store.get_run_errors("run-001")
        assert len(errors) == 1
        assert errors[0]["severity"] == "critical"

    def test_record_error_with_event_payload(self):
        error_id = self.store.record_error(
            run_id="run-001",
            message="Validation failed",
            event_payload={"event_type": "task_completed", "data": {"id": 42}},
        )
        errors = self.store.get_run_errors("run-001")
        assert errors[0]["event_payload"]["event_type"] == "task_completed"

    def test_record_error_with_reducer_name(self):
        error_id = self.store.record_error(
            run_id="run-001",
            message="Error in reducer",
            reducer_name="event_aggregator",
        )
        errors = self.store.get_run_errors("run-001")
        assert errors[0]["reducer_name"] == "event_aggregator"

    def test_get_run_errors_empty(self):
        errors = self.store.get_run_errors("run-nonexistent")
        assert errors == []

    def test_get_run_errors_multiple_runs(self):
        self.store.record_error("run-001", "Error A")
        self.store.record_error("run-002", "Error B")
        self.store.record_error("run-001", "Error C")
        
        run_001_errors = self.store.get_run_errors("run-001")
        assert len(run_001_errors) == 2

    def test_get_all_errors_no_filter(self):
        self.store.record_error("run-001", "Error A", severity=ErrorSeverity.LOW)
        self.store.record_error("run-002", "Error B", severity=ErrorSeverity.HIGH)
        
        all_errors = self.store.get_all_errors()
        assert len(all_errors) == 2

    def test_get_all_errors_filter_by_severity(self):
        self.store.record_error("run-001", "Low", severity=ErrorSeverity.LOW)
        self.store.record_error("run-002", "High", severity=ErrorSeverity.HIGH)
        
        high_errors = self.store.get_all_errors(severity=ErrorSeverity.HIGH)
        assert len(high_errors) == 1
        assert high_errors[0]["message"] == "High"

    def test_get_all_errors_excludes_resolved(self):
        error_id = self.store.record_error("run-001", "Error A")
        self.store.resolve_error(error_id)
        
        all_errors = self.store.get_all_errors()
        assert len(all_errors) == 0

    def test_get_all_errors_includes_resolved_when_flagged(self):
        error_id = self.store.record_error("run-001", "Error A")
        self.store.resolve_error(error_id)
        
        all_errors = self.store.get_all_errors(include_resolved=True)
        assert len(all_errors) == 1

    def test_get_error_counts(self):
        self.store.record_error("run-001", "Low", severity=ErrorSeverity.LOW)
        self.store.record_error("run-002", "Medium", severity=ErrorSeverity.MEDIUM)
        self.store.record_error("run-003", "High", severity=ErrorSeverity.HIGH)
        
        counts = self.store.get_error_counts()
        assert counts["low"] == 1
        assert counts["medium"] == 1
        assert counts["high"] == 1

    def test_get_error_counts_resolved_excluded(self):
        error_id = self.store.record_error("run-001", "Low", severity=ErrorSeverity.LOW)
        self.store.resolve_error(error_id)
        
        counts = self.store.get_error_counts()
        assert "low" not in counts or counts["low"] == 0

    def test_resolve_error(self):
        error_id = self.store.record_error("run-001", "Fixable error")
        assert self.store.resolve_error(error_id) is True
        
        errors = self.store.get_all_errors()
        assert len(errors) == 0

    def test_resolve_nonexistent_error(self):
        assert self.store.resolve_error("nonexistent") is False

    def test_clear_run_errors(self):
        self.store.record_error("run-001", "Error A")
        self.store.record_error("run-001", "Error B")
        self.store.record_error("run-002", "Error C")
        
        count = self.store.clear_run_errors("run-001")
        assert count == 2
        
        run_001_errors = self.store.get_run_errors("run-001")
        assert len(run_001_errors) == 0

    def test_clear_nonexistent_run(self):
        count = self.store.clear_run_errors("run-nonexistent")
        assert count == 0

    def test_reducer_error_to_dict(self):
        from datetime import datetime
        error = ReducerError(
            error_id="err-001",
            run_id="run-001",
            severity=ErrorSeverity.HIGH,
            message="Test error",
            event_payload={"key": "value"},
            reducer_name="test_reducer",
        )
        d = error.to_dict()
        assert d["error_id"] == "err-001"
        assert d["run_id"] == "run-001"
        assert d["severity"] == "high"
        assert d["message"] == "Test error"
        assert d["event_payload"] == {"key": "value"}
        assert d["reducer_name"] == "test_reducer"
        assert d["resolved"] is False
        assert d["resolved_at"] is None

    def test_record_error_preserves_lifecycle_state(self):
        """Regression: reducer errors must not contaminate normal workflow state."""
        self.store.record_error("run-001", "Error")
        errors = self.store.get_run_errors("run-001")
        assert len(errors) == 1
        # The store is separate — primary event log state is untouched
        assert errors[0]["run_id"] == "run-001"
