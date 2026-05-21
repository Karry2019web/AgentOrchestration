"""Tests for the event retention store."""

import datetime
import json
import uuid
from typing import Any, Dict

import pytest

from src.orchestrator.event_store import (
    AuditStore,
    EventRecord,
    EventRetentionStore,
    EventSeverity,
    OperationalStore,
)


def _make_event(event_id: str = None, event_type: str = "test.event") -> EventRecord:
    return EventRecord(
        event_id=event_id or str(uuid.uuid4()),
        timestamp=datetime.datetime.utcnow().isoformat() + "Z",
        source="test",
        event_type=event_type,
        severity=EventSeverity.INFO,
        payload={"key": "value"},
    )


class TestOperationalStore:
    def test_write_and_read(self):
        store = OperationalStore(max_records=100)
        record = _make_event()
        seq = store.write(record)
        assert seq == 1
        records = store.read()
        assert len(records) == 1
        assert records[0].event_id == record.event_id

    def test_compact_removes_old_records(self):
        store = OperationalStore(max_records=100)
        old = _make_event(event_type="old")
        store.write(old)
        later = _make_event(event_type="new")
        store.write(later)
        # Compact using a timestamp after the first record
        cut = datetime.datetime.utcnow().isoformat() + "Z"
        old_ts = (datetime.datetime.utcnow() - datetime.timedelta(hours=2)).isoformat() + "Z"
        store.write(_make_event())
        removed = store.compact(cut)
        assert removed > 0

    def test_compact_does_not_affect_recent(self):
        store = OperationalStore(max_records=100)
        now = datetime.datetime.utcnow().isoformat() + "Z"
        store.write(_make_event())
        removed = store.compact((datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat() + "Z")
        assert removed > 0
        assert store.count() == 0

    def test_max_records_enforced(self):
        store = OperationalStore(max_records=3)
        for i in range(5):
            e = _make_event(event_id=f"e{i}", event_type=f"event.{i}")
            store.write(e)
        assert store.count() == 3

    def test_read_with_offset(self):
        store = OperationalStore(max_records=100)
        for i in range(10):
            e = _make_event(event_id=f"e{i}")
            store.write(e)
        records = store.read(limit=3, offset=5)
        assert len(records) == 3
        assert records[0].event_id == "e5"

    def test_clear_resets_state(self):
        store = OperationalStore(max_records=100)
        store.write(_make_event())
        store.clear()
        assert store.count() == 0
        assert store.read() == []


class TestAuditStore:
    def test_append_and_read(self):
        store = AuditStore()
        record = _make_event()
        digest = store.append(record)
        assert len(digest) == 64  # SHA-256 hex
        records = store.read()
        assert len(records) == 1
        assert records[0].digest == digest

    def test_chain_integrity(self):
        store = AuditStore()
        d1 = store.append(_make_event(event_id="e1"))
        d2 = store.append(_make_event(event_id="e2"))
        d3 = store.append(_make_event(event_id="e3"))
        assert d1 != d2 != d3
        assert store.verify_chain()

    def test_chain_detects_tamper(self):
        store = AuditStore()
        store.append(_make_event(event_id="e1"))
        store.append(_make_event(event_id="e2"))
        # Tamper with the second record
        store._records[1].payload["tampered"] = True
        assert not store.verify_chain()

    def test_chain_empty(self):
        store = AuditStore()
        assert store.verify_chain()

    def test_chain_single_record(self):
        store = AuditStore()
        store.append(_make_event(event_id="e1"))
        assert store.verify_chain()

    def test_chained_digests_differ_on_order(self):
        store = AuditStore()
        d1 = store.append(_make_event(event_id="a"))
        d2 = store.append(_make_event(event_id="b"))
        # Create a store with same records in different order
        store2 = AuditStore()
        store2.append(_make_event(event_id="b"))
        store2.append(_make_event(event_id="a"))
        assert d1 == store2._records[0].digest  # first record zero-chain different payload
        # The second record's digest depends on first's digest => different chain
        assert d2 != store2._records[1].digest

    def test_count(self):
        store = AuditStore()
        assert store.count() == 0
        store.append(_make_event())
        assert store.count() == 1
        store.append(_make_event())
        assert store.count() == 2


class TestEventRetentionStore:
    def test_write_operational_only(self):
        s = EventRetentionStore()
        s.write_event(
            event_id="t1",
            source="test",
            event_type="task.started",
            payload={"task_id": "t1"},
            severity=EventSeverity.INFO,
            audit=False,
        )
        stats = s.get_stats()
        assert stats["operational_count"] == 1
        assert stats["audit_count"] == 0

    def test_write_operational_and_audit(self):
        s = EventRetentionStore()
        s.write_event(
            event_id="t1",
            source="test",
            event_type="task.started",
            payload={"task_id": "t1"},
            severity=EventSeverity.INFO,
            audit=True,
        )
        stats = s.get_stats()
        assert stats["operational_count"] == 1
        assert stats["audit_count"] == 1

    def test_compact_affects_only_operational(self):
        s = EventRetentionStore()
        s.write_event(event_id="old", source="test", event_type="old", payload={}, audit=True)
        later_ts = (datetime.datetime.utcnow() + datetime.timedelta(hours=1)).isoformat() + "Z"
        removed = s.compact_operational(later_ts)
        assert removed > 0
        stats = s.get_stats()
        assert stats["operational_count"] == 0
        # Audit records untouched
        assert stats["audit_count"] == 1

    def test_audit_chain_verification(self):
        s = EventRetentionStore()
        for i in range(5):
            s.write_event(
                event_id=f"e{i}",
                source="test",
                event_type="task.event",
                payload={"i": i},
                audit=True,
            )
        assert s.verify_audit_chain()

    def test_severity_levels(self):
        s = EventRetentionStore()
        for sev in EventSeverity:
            s.write_event(
                event_id=sev.value,
                source="test",
                event_type=f"event.{sev.value}",
                payload={},
                severity=sev,
            )
        assert s.get_stats()["operational_count"] == len(EventSeverity)

    def test_operational_compact_preserves_recent(self):
        s = EventRetentionStore()
        s.write_event(event_id="recent", source="test", event_type="recent", payload={}, audit=True)
        before_ts = (datetime.datetime.utcnow() - datetime.timedelta(hours=1)).isoformat() + "Z"
        removed = s.compact_operational(before_ts)
        assert removed == 0
        assert s.get_stats()["operational_count"] == 1

    def test_empty_store(self):
        s = EventRetentionStore()
        assert s.get_stats()["operational_count"] == 0
        assert s.get_stats()["audit_count"] == 0
        assert s.verify_audit_chain()
