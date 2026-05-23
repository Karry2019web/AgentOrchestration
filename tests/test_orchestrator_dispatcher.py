"""Tests for the event dispatcher — quarantine during rolling version upgrades."""

import pytest
from src.orchestrator.dispatcher import (
    EventDispatcher,
    EventDispatchError,
    EventType,
    QuarantineEvent,
)


class TestEventDispatcher:
    def setup_method(self):
        self.dispatcher = EventDispatcher()

    def test_known_event_dispatched(self):
        """A known event type with valid payload dispatches successfully."""
        result = self.dispatcher.dispatch(
            EventType.ATTEMPT.value,
            {"attempt": 1, "revision": 1},
        )
        assert result is True

    def test_unknown_event_quarantined(self):
        """An unknown event type is quarantined, not dispatched."""
        result = self.dispatcher.dispatch("unknown.event", {})
        assert result is False
        assert self.dispatcher.quarantine_count == 1
        assert self.dispatcher.quarantine[0].event_type == "unknown.event"

    def test_stale_revision_quarantined(self):
        """An event with a stale revision is quarantined."""
        self.dispatcher.advance_revision(5)
        result = self.dispatcher.dispatch(
            EventType.REVISION.value,
            {"revision": 3},
            expected_revision=3,
        )
        assert result is False
        assert self.dispatcher.quarantine_count == 1

    def test_advance_revision_refuses_non_increasing(self):
        """advance_revision ignores non-increasing values."""
        self.dispatcher.advance_revision(5)
        self.dispatcher.advance_revision(3)  # Should be ignored
        result = self.dispatcher.dispatch(
            EventType.REVISION.value,
            {"revision": 4},
            expected_revision=4,
        )
        assert result is False  # Stale because current is 5

    def test_handler_executed(self):
        """Registered handlers are called on dispatch."""
        events = []

        def handler(event_type, payload):
            events.append((event_type, payload))

        self.dispatcher.register_handler(EventType.SCHEDULE.value, handler)
        self.dispatcher.dispatch(EventType.SCHEDULE.value, {"task": "test"})
        assert len(events) == 1
        assert events[0][0] == EventType.SCHEDULE.value

    def test_multiple_handlers_per_type(self):
        """Multiple handlers can be registered for the same event type."""
        calls = []

        def handler_a(et, p):
            calls.append("a")

        def handler_b(et, p):
            calls.append("b")

        self.dispatcher.register_handler(EventType.ATTEMPT.value, handler_a)
        self.dispatcher.register_handler(EventType.ATTEMPT.value, handler_b)
        self.dispatcher.dispatch(EventType.ATTEMPT.value, {})
        assert calls == ["a", "b"]

    def test_quarantine_cleared_by_flush(self):
        """flush_quarantine returns and empties the quarantine list."""
        self.dispatcher.dispatch("unknown.one", {})
        self.dispatcher.dispatch("unknown.two", {})
        assert self.dispatcher.quarantine_count == 2
        flushed = self.dispatcher.flush_quarantine()
        assert len(flushed) == 2
        assert self.dispatcher.quarantine_count == 2  # count is cumulative
        assert len(self.dispatcher.quarantine) == 0

    def test_complete_upgrade_flags_inactive(self):
        """After complete_upgrade, rolling upgrade flag is cleared."""
        assert self.dispatcher._rolling_upgrade_active is True
        self.dispatcher.complete_upgrade()
        assert self.dispatcher._rolling_upgrade_active is False

    def test_dispatches_known_lifecycle_events(self):
        """All lifecycle event types dispatch successfully."""
        for event_type in EventType:
            result = self.dispatcher.dispatch(event_type.value, {})
            assert result is True, f"{event_type.value} should dispatch"

    def test_policy_violation_lifecycle_start_while_running(self):
        """Starting a lifecycle for an already-running state is quarantined."""
        result = self.dispatcher.dispatch(
            EventType.LIFECYCLE_START.value,
            {"state": "running"},
        )
        assert result is False
        assert self.dispatcher.quarantine_count == 1

    def test_policy_violation_complete_while_pending(self):
        """Completing a lifecycle from pending state is quarantined."""
        result = self.dispatcher.dispatch(
            EventType.LIFECYCLE_COMPLETE.value,
            {"state": "pending"},
        )
        assert result is False

    def test_event_with_both_attempt_and_revision(self):
        """Events with both attempt and revision markers dispatch during upgrade."""
        result = self.dispatcher.dispatch(
            EventType.WORKFLOW_START.value,
            {"attempt": 42, "revision": 1},
        )
        assert result is True

    def test_quarantine_event_repr(self):
        """QuarantineEvent repr is informative."""
        event = QuarantineEvent("test.type", {"key": "val"}, "test reason")
        text = repr(event)
        assert "test.type" in text
        assert "test reason" in text
