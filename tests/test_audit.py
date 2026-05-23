"""Tests for the audit trail module."""

import pytest
from src.common.audit import AuditTrail


class TestAuditTrail:
    def setup_method(self):
        self.trail = AuditTrail()

    def test_record_successful_download(self):
        event = self.trail.record_download(
            actor="alice",
            export_id="exp-001",
            success=True,
        )
        assert event["event"] == "export.download"
        assert event["actor"] == "alice"
        assert event["export_id"] == "exp-001"
        assert event["success"] is True
        assert event["error"] is None
        assert "timestamp" in event
        assert "id" in event

    def test_record_failed_download(self):
        event = self.trail.record_download(
            actor="bob",
            export_id="exp-002",
            success=False,
            error="Export not found",
        )
        assert event["success"] is False
        assert event["error"] == "Export not found"

    def test_get_events_by_export_id(self):
        self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        self.trail.record_download(actor="bob", export_id="exp-002", success=True)
        self.trail.record_download(actor="charlie", export_id="exp-001", success=False, error="Timeout")

        events = self.trail.get_events(export_id="exp-001")
        assert len(events) == 2
        assert all(e["export_id"] == "exp-001" for e in events)

    def test_get_events_by_actor(self):
        self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        self.trail.record_download(actor="alice", export_id="exp-002", success=True)
        self.trail.record_download(actor="bob", export_id="exp-003", success=True)

        events = self.trail.get_events(actor="alice")
        assert len(events) == 2
        assert all(e["actor"] == "alice" for e in events)

    def test_get_events_returns_newest_first(self):
        self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        import time
        time.sleep(0.001)
        self.trail.record_download(actor="bob", export_id="exp-002", success=True)

        events = self.trail.get_events()
        assert len(events) == 2
        assert events[0]["actor"] == "bob"

    def test_get_events_limit(self):
        for i in range(10):
            self.trail.record_download(actor=f"user{i}", export_id=f"exp-{i}", success=True)

        events = self.trail.get_events(limit=3)
        assert len(events) == 3

    def test_latest_event(self):
        assert self.trail.latest_event() is None
        self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        assert self.trail.latest_event()["actor"] == "alice"

        self.trail.record_download(actor="bob", export_id="exp-002", success=True)
        assert self.trail.latest_event()["actor"] == "bob"

    def test_clear(self):
        self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        self.trail.clear()
        assert len(self.trail.get_events()) == 0

    def test_multiple_events_independent(self):
        e1 = self.trail.record_download(actor="alice", export_id="exp-001", success=True)
        e2 = self.trail.record_download(actor="bob", export_id="exp-002", success=False, error="Forbidden")

        events = self.trail.get_events()
        assert len(events) == 2
        assert e1["id"] != e2["id"]
