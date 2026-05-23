"""Tests for the QuarantineStore."""

import time
import pytest
from src.common.quarantine import QuarantineStore


class TestQuarantineStore:
    def setup_method(self):
        self.store = QuarantineStore(retention_seconds=3600)  # 1 hour for tests

    def test_store_and_get_raw(self):
        record_id = self.store.store({"type": "task", "data": "test", "error": "invalid schema"})
        assert record_id is not None
        raw = self.store.get_raw(record_id)
        assert raw is not None
        assert raw["reason"] == "invalid schema"
        assert "payload" in raw
        assert raw["payload"]["type"] == "task"

    def test_get_raw_nonexistent(self):
        assert self.store.get_raw("nonexistent-id") is None

    def test_get_redacted_default(self):
        record_id = self.store.store({"type": "task", "data": "secret-value", "error": "bad input"})
        redacted = self.store.get_redacted(record_id)
        assert redacted is not None
        assert "payload" not in redacted
        assert "summary" in redacted
        assert redacted["summary"]["data"].startswith("[REDACTED")

    def test_list_redacted(self):
        self.store.store({"type": "task_a"})
        self.store.store({"type": "task_b"})
        records = self.store.list_redacted()
        assert len(records) == 2
        assert all("payload" not in r for r in records)
        assert all("summary" in r for r in records)

    def test_cleanup_expired_records(self):
        short_store = QuarantineStore(retention_seconds=0)
        short_store.store({"type": "ephemeral"})
        time.sleep(0.01)
        assert short_store.count() == 0
        assert short_store.get_raw("anything") is None

    def test_count(self):
        self.store.store({"type": "a"})
        self.store.store({"type": "b"})
        assert self.store.count() == 2

    def test_set_retention(self):
        self.store.set_retention(7200)
        assert self.store.get_retention() == 7200

    def test_store_with_task_id(self):
        record_id = self.store.store({"type": "test"}, task_id="task-123")
        raw = self.store.get_raw(record_id)
        assert raw["task_id"] == "task-123"
