"""Tests for run lifecycle and archived-run event rejection."""

import pytest
from src.orchestrator.engine import OrchestrationEngine, RunState, RunStatus


class TestRunState:
    def test_initial_state(self):
        rs = RunState("run-1", "wf-1")
        assert rs.status == RunStatus.PENDING
        assert rs.version == 0

    def test_valid_transition(self):
        rs = RunState("run-1", "wf-1")
        assert rs.transition_to(RunStatus.RUNNING) is True
        assert rs.status == RunStatus.RUNNING

    def test_invalid_transition_from_archived(self):
        rs = RunState("run-1", "wf-1")
        rs.transition_to(RunStatus.RUNNING)
        rs.transition_to(RunStatus.COMPLETED)
        rs.transition_to(RunStatus.ARCHIVED)
        assert rs.transition_to(RunStatus.RUNNING) is False
        assert rs.status == RunStatus.ARCHIVED

    def test_is_archived(self):
        rs = RunState("run-2", "wf-1")
        rs.transition_to(RunStatus.RUNNING)
        rs.transition_to(RunStatus.COMPLETED)
        rs.transition_to(RunStatus.ARCHIVED)
        assert rs.is_archived() is True

    def test_is_terminal(self):
        for status in [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.ARCHIVED, RunStatus.CANCELLED]:
            rs = RunState(f"run-{status.value}", "wf-1")
            rs.status = status
            assert rs.is_terminal() is True


class TestOrchestrationEngine:
    def setup_method(self):
        self.engine = OrchestrationEngine()

    def test_create_run(self):
        run_id = self.engine.create_run("wf-1")
        assert run_id is not None
        assert self.engine.get_run_status(run_id) == "pending"

    def test_archive_run(self):
        run_id = self.engine.create_run("wf-1")
        assert self.engine.archive_run(run_id) is True

    def test_dispatch_event_success(self):
        run_id = self.engine.create_run("wf-1")
        assert self.engine.dispatch_event(run_id, {"type": "test"}) is True

    def test_dispatch_event_rejected_for_archived(self):
        run_id = self.engine.create_run("wf-1")
        self.engine.archive_run(run_id)
        assert self.engine.dispatch_event(run_id, {"type": "late_msg"}) is False

    def test_dispatch_event_rejected_for_nonexistent(self):
        assert self.engine.dispatch_event("nonexistent", {"type": "test"}) is False

    def test_get_run_status_nonexistent(self):
        assert self.engine.get_run_status("nonexistent") is None
