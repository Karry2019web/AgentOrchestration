"""Tests for the ReducerErrorStore."""

import time
import pytest
from src.orchestrator.reducer_errors import (
    ReducerErrorStore,
    ReducerErrorRecord,
    ErrorSeverity,
)


@pytest.fixture
def store():
    """Create a fresh ReducerErrorStore for each test."""
    return ReducerErrorStore(max_errors_per_run=100)


class TestReducerErrorRecord:
    def test_create_record(self):
        """Test basic record creation."""
        record = ReducerErrorRecord(
            run_id="run-1",
            message="Test error",
            severity=ErrorSeverity.ERROR,
            event_payload={"event": "test"},
            context={"step": "validate"},
        )
        assert record.run_id == "run-1"
        assert record.message == "Test error"
        assert record.severity == ErrorSeverity.ERROR
        assert record.event_payload == {"event": "test"}
        assert record.context == {"step": "validate"}
        assert not record.resolved
        assert record.attempt == 0
        assert record.revision == 0

    def test_to_dict(self):
        """Test serialization to dict."""
        record = ReducerErrorRecord(
            run_id="run-1",
            message="Test error",
            severity=ErrorSeverity.WARNING,
            event_payload={"key": "value"},
        )
        d = record.to_dict()
        assert d["run_id"] == "run-1"
        assert d["severity"] == "warning"
        assert d["event_payload"] == {"key": "value"}
        assert d["resolved"] is False
        assert d["attempt"] == 0
        assert "id" in d
        assert "timestamp" in d


class TestReducerErrorStore:
    def test_record_error(self, store):
        """Test recording a basic error."""
        error = store.record_error(
            run_id="run-1",
            message="Something went wrong",
            severity=ErrorSeverity.ERROR,
            event_payload={"task_id": "t-1"},
            context={"handler": "process"},
        )
        assert error.run_id == "run-1"
        assert store.error_count == 1

    def test_get_run_errors(self, store):
        """Test retrieving errors for a specific run."""
        store.record_error("run-1", "Error 1", ErrorSeverity.WARNING)
        store.record_error("run-1", "Error 2", ErrorSeverity.ERROR)
        store.record_error("run-2", "Other error", ErrorSeverity.INFO)

        run1_errors = store.get_run_errors("run-1")
        assert len(run1_errors) == 2

        run2_errors = store.get_run_errors("run-2")
        assert len(run2_errors) == 1

    def test_get_all_errors(self, store):
        """Test global error retrieval."""
        store.record_error("run-1", "Error A", ErrorSeverity.WARNING)
        store.record_error("run-2", "Error B", ErrorSeverity.ERROR)

        all_errors = store.get_all_errors()
        assert len(all_errors) == 2

    def test_get_all_errors_filter_by_severity(self, store):
        """Test filtering errors by severity."""
        store.record_error("run-1", "Warning", ErrorSeverity.WARNING)
        store.record_error("run-1", "Error", ErrorSeverity.ERROR)
        store.record_error("run-2", "Info", ErrorSeverity.INFO)

        warnings = store.get_all_errors(severity="warning")
        assert len(warnings) == 1
        assert warnings[0].message == "Warning"

        errors = store.get_all_errors(severity="error")
        assert len(errors) == 1
        assert errors[0].message == "Error"

    def test_get_error_counts(self, store):
        """Test aggregated error counts."""
        store.record_error("run-1", "Warn", ErrorSeverity.WARNING)
        store.record_error("run-1", "Err1", ErrorSeverity.ERROR)
        store.record_error("run-2", "Err2", ErrorSeverity.ERROR)
        store.record_error("run-2", "Crit", ErrorSeverity.CRITICAL)

        counts = store.get_error_counts()
        assert counts["total"] == 4
        assert counts["warning"] == 1
        assert counts["error"] == 2
        assert counts["critical"] == 1

    def test_resolve_error(self, store):
        """Test resolving a single error."""
        error = store.record_error("run-1", "Fixable error", ErrorSeverity.WARNING)
        assert not error.resolved

        result = store.resolve_error(error.id)
        assert result is True
        assert error.resolved is True
        assert error.resolved_at is not None

    def test_resolve_nonexistent_error(self, store):
        """Test resolving a non-existent error returns False."""
        result = store.resolve_error("nonexistent-id")
        assert result is False

    def test_clear_run_errors(self, store):
        """Test clearing all errors for a specific run."""
        store.record_error("run-1", "Err1", ErrorSeverity.ERROR)
        store.record_error("run-1", "Err2", ErrorSeverity.ERROR)
        store.record_error("run-2", "Other", ErrorSeverity.INFO)

        count = store.clear_run_errors("run-1")
        assert count == 2
        assert store.error_count == 1
        assert len(store.get_run_errors("run-1")) == 0

    def test_clear_all(self, store):
        """Test clearing all errors."""
        store.record_error("run-1", "Err", ErrorSeverity.ERROR)
        store.record_error("run-2", "Err", ErrorSeverity.WARNING)
        assert store.error_count == 2

        count = store.clear_all()
        assert count == 2
        assert store.error_count == 0
        assert store.run_count == 0

    def test_max_errors_per_run(self, store):
        """Test that per-run capacity is enforced."""
        for i in range(105):
            store.record_error(
                "run-1",
                f"Error {i}",
                ErrorSeverity.WARNING,
                event_payload={"index": i},
            )

        # Should have at most max_errors_per_run errors for this run
        run_errors = store.get_run_errors("run-1")
        assert len(run_errors) == 100
        assert store.error_count == 100

    # ---- Guard / Transition Validation Tests ----

    def test_reject_stale_attempt(self, store):
        """Test rejecting a transition with a stale (lower) attempt number."""
        store.record_error("run-1", "First attempt", ErrorSeverity.INFO,
                          attempt=2, revision=0, lifecycle="running")

        with pytest.raises(ValueError, match="Stale transition"):
            store.record_error("run-1", "Stale attempt", ErrorSeverity.WARNING,
                              attempt=1, revision=0, lifecycle="running")

    def test_reject_stale_revision(self, store):
        """Test rejecting a transition with a stale revision (same attempt)."""
        store.record_error("run-1", "Rev 2", ErrorSeverity.INFO,
                          attempt=1, revision=2, lifecycle="running")

        with pytest.raises(ValueError, match="Stale transition"):
            store.record_error("run-1", "Stale revision", ErrorSeverity.WARNING,
                              attempt=1, revision=1, lifecycle="running")

    def test_reject_duplicate_transition(self, store):
        """Test rejecting a duplicate transition (same attempt + revision)."""
        store.record_error("run-1", "Original", ErrorSeverity.INFO,
                          attempt=1, revision=1, lifecycle="running")

        with pytest.raises(ValueError, match="Duplicate transition"):
            store.record_error("run-1", "Duplicate", ErrorSeverity.WARNING,
                              attempt=1, revision=1, lifecycle="running")

    def test_reject_invalid_lifecycle(self, store):
        """Test rejecting a transition with an invalid lifecycle state."""
        with pytest.raises(ValueError, match="Invalid lifecycle"):
            store.record_error("run-1", "Bad lifecycle", ErrorSeverity.ERROR,
                              attempt=1, revision=0, lifecycle="unknown_state")

    def test_reject_completed_to_running_no_new_attempt(self, store):
        """Test rejecting completed→running without a new attempt."""
        store.record_error("run-1", "Completed", ErrorSeverity.INFO,
                          attempt=1, revision=1, lifecycle="completed")

        with pytest.raises(ValueError, match="Lifecycle violation"):
            store.record_error("run-1", "Try running again", ErrorSeverity.WARNING,
                              attempt=1, revision=2, lifecycle="running")

    def test_allow_completed_to_running_new_attempt(self, store):
        """Test allowing completed→running with a new attempt."""
        store.record_error("run-1", "Completed", ErrorSeverity.INFO,
                          attempt=1, revision=1, lifecycle="completed")

        # A new attempt (2) should be accepted
        error = store.record_error("run-1", "New attempt", ErrorSeverity.INFO,
                                  attempt=2, revision=0, lifecycle="running")
        assert error is not None
        assert error.attempt == 2

    def test_reject_cancelled_to_other(self, store):
        """Test rejecting transitions from cancelled to any other state."""
        store.record_error("run-1", "Cancelled", ErrorSeverity.INFO,
                          attempt=1, revision=1, lifecycle="cancelled")

        with pytest.raises(ValueError, match="Lifecycle violation"):
            store.record_error("run-1", "Try revive", ErrorSeverity.WARNING,
                              attempt=2, revision=0, lifecycle="running")

    def test_accept_forward_transition(self, store):
        """Test accepting a normal forward transition."""
        error = store.record_error("run-1", "Pending→Running", ErrorSeverity.INFO,
                                  attempt=1, revision=1, lifecycle="running")
        assert error is not None

        # Same attempt, next revision
        error2 = store.record_error("run-1", "Running→Completed", ErrorSeverity.INFO,
                                   attempt=1, revision=2, lifecycle="completed")
        assert error2 is not None
        assert error2.attempt == 1
        assert error2.revision == 2

    def test_attempt_revision_tracking(self, store):
        """Test that attempt and revision tracking advances correctly."""
        store.record_error("run-1", "Attempt 1 rev 1", ErrorSeverity.INFO,
                          attempt=1, revision=1, lifecycle="running")
        store.record_error("run-1", "Attempt 1 rev 2", ErrorSeverity.INFO,
                          attempt=1, revision=2, lifecycle="completed")
        store.record_error("run-1", "Attempt 2 rev 0", ErrorSeverity.INFO,
                          attempt=2, revision=0, lifecycle="running")
        store.record_error("run-1", "Attempt 2 rev 1", ErrorSeverity.INFO,
                          attempt=2, revision=1, lifecycle="completed")

        run_errors = store.get_run_errors("run-1")
        assert len(run_errors) == 4

    def test_get_error_counts_resolved(self, store):
        """Test error counts include resolved status."""
        e1 = store.record_error("run-1", "Err1", ErrorSeverity.ERROR)
        e2 = store.record_error("run-1", "Err2", ErrorSeverity.WARNING)
        store.resolve_error(e1.id)

        counts = store.get_error_counts()
        assert counts["resolved"] == 1
        assert counts["total"] == 2
        assert counts["error"] == 1
        assert counts["warning"] == 1

    def test_clear_run_clears_tracking_state(self, store):
        """Test that clearing a run also clears attempt/revision/lifecycle tracking."""
        store.record_error("run-1", "Err", ErrorSeverity.ERROR,
                          attempt=3, revision=5, lifecycle="completed")
        store.clear_run_errors("run-1")

        # After clearing, a new transition with lower attempt should be accepted
        error = store.record_error("run-1", "New run", ErrorSeverity.INFO,
                                  attempt=1, revision=0, lifecycle="running")
        assert error is not None
        assert error.attempt == 1
