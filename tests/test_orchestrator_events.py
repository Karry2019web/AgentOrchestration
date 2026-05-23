"""Deterministic regression tests for orchestrator event quarantine."""

import pytest
from src.orchestrator.events import (
    EventQuarantine,
    EventType,
    LifecycleRevision,
)


class TestEventType:
    """Known event types are stable and recognised."""

    def test_known_types_contains_all_event_types(self):
        known = EventType.known_types()
        for et in EventType:
            assert et.value in known

    def test_unknown_type_not_known(self):
        assert "task.unknown" not in EventType.known_types()
        assert "" not in EventType.known_types()


class TestLifecycleRevision:
    """Attempt, revision, and lifecycle guards."""

    def test_same_version_increasing_revision_allowed(self):
        current = LifecycleRevision(revision=5, version="2.0.0")
        target = LifecycleRevision(revision=6, version="2.0.0")
        assert target.allowed(current)

    def test_same_version_equal_revision_rejected(self):
        current = LifecycleRevision(revision=5, version="2.0.0")
        target = LifecycleRevision(revision=5, version="2.0.0")
        assert not target.allowed(current)

    def test_same_version_decreasing_revision_rejected(self):
        current = LifecycleRevision(revision=5, version="2.0.0")
        target = LifecycleRevision(revision=4, version="2.0.0")
        assert not target.allowed(current)

    def test_different_version_active_lifecycle_first_attempt_allowed(self):
        current = LifecycleRevision(revision=5, lifecycle="active", version="2.0.0")
        target = LifecycleRevision(attempt=1, revision=1, lifecycle="active", version="3.0.0")
        assert target.allowed(current)

    def test_different_version_retry_rejected(self):
        current = LifecycleRevision(revision=5, lifecycle="active", version="2.0.0")
        target = LifecycleRevision(attempt=2, revision=1, lifecycle="active", version="3.0.0")
        assert not target.allowed(current)

    def test_different_version_inactive_lifecycle_rejected(self):
        current = LifecycleRevision(revision=5, lifecycle="paused", version="2.0.0")
        target = LifecycleRevision(attempt=1, revision=1, lifecycle="active", version="3.0.0")
        assert not target.allowed(current)

    def test_round_trip_to_dict(self):
        rev = LifecycleRevision(attempt=3, revision=7, lifecycle="active", version="4.0.0")
        data = rev.to_dict()
        restored = LifecycleRevision.from_dict(data)
        assert restored.attempt == 3
        assert restored.revision == 7
        assert restored.lifecycle == "active"
        assert restored.version == "4.0.0"


class TestEventQuarantine:
    """Quarantine rejects unknown / version-mismatched events."""

    def setup_method(self):
        self.q = EventQuarantine()

    def test_accepts_known_event_type_in_same_version(self):
        rev = LifecycleRevision(revision=2, version="1.0.0")
        current = LifecycleRevision(revision=1, version="1.0.0")
        assert self.q.accepts(EventType.TASK_SUBMITTED.value, rev, current)

    def test_rejects_unknown_event_type(self):
        rev = LifecycleRevision(revision=2, version="1.0.0")
        current = LifecycleRevision(revision=1, version="1.0.0")
        assert not self.q.accepts("completely.unknown", rev, current)

    def test_rejects_event_with_stale_revision(self):
        rev = LifecycleRevision(revision=1, version="1.0.0")
        current = LifecycleRevision(revision=5, version="1.0.0")
        assert not self.q.accepts(EventType.TASK_SUBMITTED.value, rev, current)

    def test_quarantine_records_event(self):
        event = {"id": "abc", "type": "unknown.event"}
        self.q.quarantine(event, "unknown type")
        assert self.q.quarantine_count == 1
        assert len(self.q.quarantined) == 1
        assert self.q.quarantined[0]["event"]["id"] == "abc"
        assert "unknown type" in self.q.quarantined[0]["reason"]

    def test_clear_quarantine_resets(self):
        self.q.quarantine({"id": "x"}, "test")
        self.q.clear_quarantine()
        assert self.q.quarantine_count == 0
        assert len(self.q.quarantined) == 0

    def test_quarantine_multiple_events(self):
        for i in range(5):
            self.q.quarantine({"id": str(i)}, f"reason-{i}")
        assert self.q.quarantine_count == 5

    def test_register_new_event_type(self):
        self.q.register_event_type("custom.plugin.event")
        rev = LifecycleRevision(revision=2, version="1.0.0")
        current = LifecycleRevision(revision=1, version="1.0.0")
        assert self.q.accepts("custom.plugin.event", rev, current)


class TestEventQuarantineRollingUpgrade:
    """The rolling version upgrades trigger — core acceptance criteria."""

    def test_quarantine_unknown_event_during_upgrade(self):
        """During a rolling upgrade, unknown event types are quarantined."""
        q = EventQuarantine()
        current = LifecycleRevision(revision=10, lifecycle="active", version="1.0.0")

        # A task from the "new" version uses a yet-unknown event type
        task_rev = LifecycleRevision(attempt=1, revision=1, lifecycle="active", version="2.0.0")
        accepted = q.accepts("task.unknown_new_type", task_rev, current)

        assert not accepted, "Unknown event type during upgrade should be rejected"

    def test_quarantine_stale_event_during_upgrade(self):
        """During a rolling upgrade, stale (retry) events are quarantined."""
        q = EventQuarantine()
        current = LifecycleRevision(revision=10, lifecycle="active", version="1.0.0")

        # A retry (attempt>1) from the new version
        task_rev = LifecycleRevision(attempt=2, revision=1, lifecycle="active", version="2.0.0")
        accepted = q.accepts(EventType.TASK_SUBMITTED.value, task_rev, current)

        assert not accepted, "Stale retry event during upgrade should be rejected"

    def test_accepts_valid_event_during_upgrade(self):
        """Valid first-attempt known events pass during upgrade."""
        q = EventQuarantine()
        current = LifecycleRevision(revision=10, lifecycle="active", version="1.0.0")

        task_rev = LifecycleRevision(attempt=1, revision=11, lifecycle="active", version="1.0.0")
        accepted = q.accepts(EventType.TASK_SUBMITTED.value, task_rev, current)

        assert accepted, "Valid known event during upgrade should pass"

    def test_quarantine_counters_logged(self):
        """Quarantine events are observable via counters."""
        q = EventQuarantine()
        current = LifecycleRevision(revision=5, lifecycle="active", version="1.0.0")

        q.quarantine({"id": "t1", "type": "unknown"}, "unknown type")
        q.quarantine({"id": "t2", "type": "no_match"}, "version mismatch")

        assert q.quarantine_count == 2
        assert len(q.quarantined) == 2

    def test_preserves_expected_lifecycle_state(self):
        """After quarantine, the orchestrator's lifecycle state is unchanged."""
        q = EventQuarantine()
        current = LifecycleRevision(revision=10, lifecycle="active", version="1.0.0")

        before_revision = current.revision
        before_lifecycle = current.lifecycle
        before_version = current.version

        # Quarantine an event — this should NOT mutate the revision
        q.quarantine({"id": "test"}, "test")
        accepted = q.accepts("unknown.event", LifecycleRevision(attempt=1, revision=1, lifecycle="active", version="2.0.0"), current)

        assert not accepted
        assert current.revision == before_revision
        assert current.lifecycle == before_lifecycle
        assert current.version == before_version
