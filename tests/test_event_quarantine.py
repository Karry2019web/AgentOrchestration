"""Tests for EventQuarantine during rolling version upgrades."""
import pytest
from src.orchestrator.event_quarantine import (
    EventQuarantine,
    OrchestratorEvent,
    DispatchDecision,
    QuarantineReason,
)


def make_event(
    event_type="task.created",
    stream_id="stream-1",
    attempt_id="attempt-1",
    revision=1,
    lifecycle_state=None,
):
    return OrchestratorEvent(
        event_type=event_type,
        stream_id=stream_id,
        attempt_id=attempt_id,
        revision=revision,
        lifecycle_state=lifecycle_state,
    )


class TestEventQuarantine:
    def test_accepts_known_event_type(self):
        q = EventQuarantine(known_event_types=["task.created"])
        result = q.evaluate(make_event(event_type="task.created"))
        assert result.decision == DispatchDecision.ACCEPTED

    def test_quarantines_unknown_event_type(self):
        q = EventQuarantine(known_event_types=["task.created"])
        result = q.evaluate(make_event(event_type="task.deleted"))
        assert result.decision == DispatchDecision.QUARANTINED
        assert result.reason == QuarantineReason.UNKNOWN_EVENT_TYPE

    def test_rejects_stale_revision(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(revision=5))
        result = q.evaluate(make_event(revision=3))
        assert result.decision == DispatchDecision.QUARANTINED
        assert result.reason == QuarantineReason.STALE_REVISION

    def test_accepts_newer_revision(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(revision=1))
        result = q.evaluate(make_event(revision=2))
        assert result.decision == DispatchDecision.ACCEPTED

    def test_rejects_same_revision(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(revision=5))
        result = q.evaluate(make_event(revision=5))
        assert result.decision == DispatchDecision.QUARANTINED

    def test_deferred_during_upgrade(self):
        q = EventQuarantine(
            known_event_types=["task.created"],
            upgrade_version="2.0.0",
        )
        result = q.evaluate(make_event(revision=100))
        assert result.decision == DispatchDecision.DEFERRED

    def test_replays_deferred_after_upgrade(self):
        q = EventQuarantine(
            known_event_types=["task.created"],
            upgrade_version="2.0.0",
        )
        q.evaluate(make_event(revision=100, event_type="task.created"))
        deferred = q.complete_upgrade()
        assert len(deferred) == 1
        assert deferred[0].event_type == "task.created"

    def test_audit_log_no_private_payload(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(event_type="unknown.type"))
        entry = q.get_audit_log()[0]
        assert "payload" not in entry
        assert entry["decision"] == DispatchDecision.QUARANTINED.value

    def test_quarantine_count(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(event_type="bad.type"))
        q.evaluate(make_event(event_type="worse.type"))
        assert q.get_quarantine_count() == 2

    def test_multiple_streams_independent(self):
        q = EventQuarantine(known_event_types=["task.created"])
        q.evaluate(make_event(stream_id="a", revision=1))
        result = q.evaluate(make_event(stream_id="b", revision=1))
        assert result.decision == DispatchDecision.ACCEPTED

    def test_empty_known_types(self):
        q = EventQuarantine(known_event_types=[])
        result = q.evaluate(make_event(event_type="anything"))
        assert result.decision == DispatchDecision.QUARANTINED

    def test_complete_upgrade_clears_deferred(self):
        q = EventQuarantine(
            known_event_types=["task.created"],
            upgrade_version="2.0.0",
        )
        q.evaluate(make_event(revision=100))
        assert q.get_deferred_count() == 1
        q.complete_upgrade()
        assert q.get_deferred_count() == 0
