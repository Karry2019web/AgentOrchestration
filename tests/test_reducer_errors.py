"""Tests for the reducer error store."""

import pytest
from src.orchestrator.reducer_errors import ReducerErrorStore, ReducerErrorSeverity


class TestReducerErrorStore:
    def setup_method(self):
        self.store = ReducerErrorStore()

    def test_record_error(self):
        eid = self.store.record_error("run-1", "task_reducer", "ValueError",
                                       "Missing field", ReducerErrorSeverity.ERROR, {"t": "1"}, 1)
        assert eid is not None
        errors = self.store.get_run_errors("run-1")
        assert len(errors) == 1
        assert errors[0]["reducer_name"] == "task_reducer"

    def test_get_run_errors_empty(self):
        assert self.store.get_run_errors("nonexistent") == []

    def test_filter_by_severity(self):
        self.store.record_error("r1", "a", "Err", "w1", ReducerErrorSeverity.WARNING)
        self.store.record_error("r2", "b", "Err", "e1", ReducerErrorSeverity.ERROR)
        criticals = self.store.get_all_errors(ReducerErrorSeverity.CRITICAL)
        assert len(criticals) == 0
        warnings = self.store.get_all_errors(ReducerErrorSeverity.WARNING)
        assert len(warnings) == 1

    def test_get_error_counts(self):
        self.store.record_error("r1", "a", "Err", "m1", ReducerErrorSeverity.WARNING)
        self.store.record_error("r2", "b", "Err", "m2", ReducerErrorSeverity.ERROR)
        counts = self.store.get_error_counts()
        assert counts["total"] == 2
        assert counts.get("warning") == 1
        assert counts.get("error") == 1

    def test_resolve_error(self):
        eid = self.store.record_error("r1", "a", "Err", "msg")
        assert self.store.resolve_error(eid) is True
        assert self.store.resolve_error("nonexistent") is False

    def test_clear_run_errors(self):
        self.store.record_error("r1", "a", "Err", "m1")
        self.store.record_error("r1", "b", "Err", "m2")
        assert self.store.clear_run_errors("r1") == 2
        assert self.store.get_run_errors("r1") == []
