"""Tests for the orchestrator reducer error store and lifecycle guards."""

import pytest
from src.orchestrator.engine import (
    ReducerErrorStore,
    ReducerTransition,
    TransitionError,
    LifecycleState,
)


class TestReducerErrorStore:
    def setup_method(self):
        self.store = ReducerErrorStore()

    def test_initial_state(self):
        assert self.store.get_state("nonexistent") == LifecycleState.PENDING
        assert self.store.get_attempt("nonexistent") == 0
        assert self.store.get_revision("nonexistent") == 0

    def test_valid_pending_to_running(self):
        transition = ReducerTransition(
            entity_id="task-1",
            from_state=LifecycleState.PENDING,
            to_state=LifecycleState.RUNNING,
            attempt=1,
            revision=1,
        )
        assert self.store.validate_transition(transition) is True
        self.store.commit_transition(transition)
        assert self.store.get_state("task-1") == LifecycleState.RUNNING

    def test_stale_attempt_rejected(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.COMPLETED, attempt=1, revision=2)
        with pytest.raises(TransitionError, match="Stale attempt"):
            self.store.validate_transition(t2)

    def test_stale_revision_rejected(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=3)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.COMPLETED, attempt=2, revision=1)
        with pytest.raises(TransitionError, match="Stale revision"):
            self.store.validate_transition(t2)

    def test_completed_to_failed_rejected(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.COMPLETED, attempt=2, revision=2)
        self.store.validate_transition(t2)
        self.store.commit_transition(t2)

        t3 = ReducerTransition("task-1", LifecycleState.COMPLETED, LifecycleState.FAILED, attempt=3, revision=3)
        with pytest.raises(TransitionError, match="already completed"):
            self.store.validate_transition(t3)

    def test_cancelled_blocks_any_transition(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.CANCELLED, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.CANCELLED, LifecycleState.RUNNING, attempt=2, revision=2)
        with pytest.raises(TransitionError, match="cancelled"):
            self.store.validate_transition(t2)

    def test_rollback_allows_pending(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.ROLLING_BACK, attempt=2, revision=2)
        self.store.validate_transition(t2)
        self.store.commit_transition(t2)

        t3 = ReducerTransition("task-1", LifecycleState.ROLLING_BACK, LifecycleState.PENDING, attempt=3, revision=3)
        self.store.validate_transition(t3)
        self.store.commit_transition(t3)
        assert self.store.get_state("task-1") == LifecycleState.PENDING

    def test_rollback_cant_skip_to_running(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.ROLLING_BACK, attempt=2, revision=2)
        self.store.validate_transition(t2)
        self.store.commit_transition(t2)

        t3 = ReducerTransition("task-1", LifecycleState.ROLLING_BACK, LifecycleState.RUNNING, attempt=3, revision=3)
        with pytest.raises(TransitionError, match="complete rollback"):
            self.store.validate_transition(t3)

    def test_record_and_retrieve_errors(self):
        self.store.record_error("task-1", "test_trigger", "Something went wrong")
        errors = self.store.get_errors("task-1")
        assert len(errors) == 1
        assert errors[0]["entity_id"] == "task-1"
        assert errors[0]["error"] == "Something went wrong"

    def test_clear_errors(self):
        self.store.record_error("task-1", "trigger-1", "error-1")
        self.store.record_error("task-2", "trigger-2", "error-2")
        self.store.clear_errors("task-1")
        assert len(self.store.get_errors("task-1")) == 0
        assert len(self.store.get_errors("task-2")) == 1

    def test_get_errors_empty(self):
        assert self.store.get_errors("nonexistent") == []
        assert self.store.get_errors() == []

    def test_full_lifecycle_flow(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        assert self.store.validate_transition(t1) is True
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.COMPLETED, attempt=2, revision=2)
        assert self.store.validate_transition(t2) is True
        self.store.commit_transition(t2)

        assert self.store.get_state("task-1") == LifecycleState.COMPLETED

    def test_failed_then_retry(self):
        t1 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=1, revision=1)
        self.store.validate_transition(t1)
        self.store.commit_transition(t1)

        t2 = ReducerTransition("task-1", LifecycleState.RUNNING, LifecycleState.FAILED, attempt=2, revision=2)
        self.store.validate_transition(t2)
        self.store.commit_transition(t2)

        t3 = ReducerTransition("task-1", LifecycleState.FAILED, LifecycleState.PENDING, attempt=3, revision=3)
        assert self.store.validate_transition(t3) is True
        self.store.commit_transition(t3)

        t4 = ReducerTransition("task-1", LifecycleState.PENDING, LifecycleState.RUNNING, attempt=4, revision=4)
        assert self.store.validate_transition(t4) is True
        self.store.commit_transition(t4)
        assert self.store.get_state("task-1") == LifecycleState.RUNNING
