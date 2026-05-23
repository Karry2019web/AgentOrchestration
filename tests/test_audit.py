"""Tests for audit trail and export download endpoints."""

import pytest
from src.common.logging import AuditTrail, audit


class TestAuditTrail:
    def setup_method(self):
        self.audit = AuditTrail()

    def test_record_download_event(self):
        event = self.audit.record(
            action="export.download",
            actor="user-123",
            target_id="export-abc",
            target_type="export",
            result="success",
        )
        assert event["action"] == "export.download"
        assert event["actor"] == "user-123"
        assert event["target_id"] == "export-abc"
        assert event["result"] == "success"
        assert "timestamp" in event

    def test_record_failed_download(self):
        event = self.audit.record(
            action="export.download",
            actor="user-456",
            target_id="export-nonexistent",
            target_type="export",
            result="failure",
            metadata={"reason": "export_not_found"},
        )
        assert event["result"] == "failure"
        assert event["metadata"]["reason"] == "export_not_found"

    def test_query_by_actor(self):
        self.audit.record("export.download", "alice", "e1", "export", "success")
        self.audit.record("export.download", "bob", "e2", "export", "success")
        self.audit.record("export.create", "alice", "e3", "export", "success")
        results = self.audit.query(actor="alice")
        assert len(results) == 2
        assert all(e["actor"] == "alice" for e in results)

    def test_query_by_target_type(self):
        self.audit.record("export.download", "alice", "e1", "export", "success")
        self.audit.record("agent.start", "alice", "a1", "agent", "success")
        results = self.audit.query(target_type="export")
        assert len(results) == 1
        assert results[0]["target_type"] == "export"

    def test_query_by_action(self):
        self.audit.record("export.download", "alice", "e1", "export", "success")
        self.audit.record("export.create", "alice", "e2", "export", "success")
        results = self.audit.query(action="export.download")
        assert len(results) == 1
        assert results[0]["action"] == "export.download"

    def test_clear_events(self):
        self.audit.record("export.download", "alice", "e1", "export", "success")
        assert len(self.audit.query()) == 1
        self.audit.clear()
        assert len(self.audit.query()) == 0

    def test_limit_query(self):
        for i in range(10):
            self.audit.record("export.download", "alice", f"e{i}", "export", "success")
        results = self.audit.query(limit=3)
        assert len(results) == 3
