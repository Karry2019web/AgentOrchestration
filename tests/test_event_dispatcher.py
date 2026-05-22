"""Tests for EventDispatcher event type validation and quarantine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.orchestrator.engine import EventDispatcher, KNOWN_EVENT_TYPES


class TestEventDispatcher:
    def setup_method(self):
        self.dispatcher = EventDispatcher()

    def test_known_event_types_accepted(self):
        for event_type in ["task.submit", "task.complete", "workflow.start"]:
            decision = self.dispatcher.validate_event({
                "id": f"evt-{event_type}",
                "type": event_type,
                "tenant_id": "tenant-1",
                "revision": 1,
            })
            assert decision["accepted"] is True, f"{event_type} should be accepted"
            assert decision["reason"] == "ok"

    def test_unknown_event_type_quarantined(self):
        decision = self.dispatcher.validate_event({
            "id": "evt-1",
            "type": "unknown.custom.v2",
            "tenant_id": "tenant-1",
            "revision": 1,
        })
        assert decision["accepted"] is False
        assert decision["reason"] == "unknown_event_type"
        assert decision["quarantine"] is True

    def test_missing_event_type_rejected(self):
        decision = self.dispatcher.validate_event({
            "id": "evt-no-type",
            "tenant_id": "t1",
            "revision": 1,
        })
        assert decision["accepted"] is False
        assert decision["reason"] == "missing_event_type"

    def test_quarantined_events_are_tracked(self):
        self.dispatcher.validate_event({
            "id": "e1", "type": "bad.type", "tenant_id": "t1", "revision": 1,
        })
        self.dispatcher.validate_event({
            "id": "e2", "type": "also.bad", "tenant_id": "t2", "revision": 2,
        })
        quarantined = self.dispatcher.get_quarantined_events()
        assert len(quarantined) == 2
        assert quarantined[0]["event_type"] == "bad.type"
        assert quarantined[1]["event_type"] == "also.bad"

    def test_clear_quarantine_resets(self):
        self.dispatcher.validate_event({
            "id": "e1", "type": "bad.type", "tenant_id": "t1", "revision": 1,
        })
        count = self.dispatcher.clear_quarantine()
        assert count == 1
        assert len(self.dispatcher.get_quarantined_events()) == 0

    def test_stale_revision_rejected(self):
        self.dispatcher.validate_event({
            "id": "e1", "type": "task.submit", "tenant_id": "t1", "revision": 5,
        })
        decision = self.dispatcher.validate_event({
            "id": "e2", "type": "task.submit", "tenant_id": "t1", "revision": 3,
        })
        assert decision["accepted"] is False
        assert decision["reason"] == "stale_revision"

    def test_rolling_upgrade_new_type(self):
        assert self.dispatcher.is_known_event_type("task.submit") is True
        assert self.dispatcher.is_known_event_type("new.upgrade.type") is False
        self.dispatcher.add_known_type("new.upgrade.type")
        assert self.dispatcher.is_known_event_type("new.upgrade.type") is True

    def test_known_event_types_frozenset(self):
        assert "task.submit" in KNOWN_EVENT_TYPES
        assert "task.complete" in KNOWN_EVENT_TYPES
        assert "unknown.event.v99" not in KNOWN_EVENT_TYPES

    def test_quarantine_contains_reasons(self):
        self.dispatcher.validate_event({
            "id": "e1", "type": "bad", "tenant_id": "t1", "revision": 1,
        })
        self.dispatcher.validate_event({
            "id": "e2", "type": "task.submit", "tenant_id": "t1", "revision": 0,
        })
        q = self.dispatcher.get_quarantined_events()
        reasons = [e["reason"] for e in q]
        assert "unknown_event_type" in reasons
        assert "stale_revision" in reasons
