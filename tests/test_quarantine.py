"""Tests for the quarantine store module."""

import time
import pytest
from src.data.quarantine import QuarantineStore, QuarantineRecord


class TestQuarantineStore:
    def setup_method(self):
        self.store = QuarantineStore(retention_seconds=3600)

    def test_store_and_count(self):
        rid = self.store.store({"name": "test"}, "validation error", "test-suite")
        assert rid is not None
        assert self.store.count() == 1

    def test_store_multiple(self):
        self.store.store({"a": 1}, "err1", "src1")
        self.store.store({"b": 2}, "err2", "src2")
        assert self.store.count() == 2

    def test_get_record(self):
        rid = self.store.store({"key": "value"}, "bad schema", "api")
        record = self.store.get(rid)
        assert record is not None
        assert record.error == "bad schema"
        assert record.payload == {"key": "value"}

    def test_get_nonexistent(self):
        assert self.store.get("nonexistent-id") is None

    def test_expired_record_not_returned(self):
        store = QuarantineStore(retention_seconds=0)
        rid = store.store({"temp": "data"}, "expired", "test")
        time.sleep(0.01)
        assert store.get(rid) is None
        assert store.count() == 0

    def test_clean_expired(self):
        store = QuarantineStore(retention_seconds=0)
        store.store({"temp": "data"}, "expired", "test")
        time.sleep(0.01)
        cleaned = store.clean_expired()
        assert cleaned == 1
        assert store.count() == 0

    def test_list_redacted(self):
        self.store.store({"secret": "my-password", "user": "admin"}, "bad input", "login")
        redacted = self.store.list_redacted()
        assert len(redacted) == 1
        assert redacted[0]["redacted"] is True
        assert "payload_summary" in redacted[0]

    def test_list_raw(self):
        self.store.store({"data": "sensitive"}, "err", "test")
        raw = self.store.list_raw()
        assert len(raw) == 1
        assert raw[0]["payload"] == {"data": "sensitive"}

    def test_retention_config(self):
        config = self.store.get_retention_config()
        assert config["retention_seconds"] == 3600
        assert "active_records" in config

    def test_store_from_multiple_sources(self):
        self.store.store({"x": 1}, "err", "source-a")
        self.store.store({"y": 2}, "err", "source-b")
        records = self.store.list_redacted()
        sources = {r["source"] for r in records}
        assert sources == {"source-a", "source-b"}

    def test_empty_store(self):
        assert self.store.count() == 0
        assert self.store.list_raw() == []
        assert self.store.list_redacted() == []
        assert self.store.clean_expired() == 0


class TestQuarantineRecord:
    def test_record_defaults(self):
        record = QuarantineRecord(payload={"key": "val"}, error="err")
        assert record.id is not None
        assert record.expires_at > record.created_at
        assert record.redacted is False

    def test_is_expired(self):
        record = QuarantineRecord(payload={}, error="", expires_at=time.time() - 1)
        assert record.is_expired() is True

    def test_not_expired(self):
        record = QuarantineRecord(payload={}, error="", expires_at=time.time() + 3600)
        assert record.is_expired() is False

    def test_to_redacted_dict(self):
        record = QuarantineRecord(
            payload={"username": "john", "password": "secret123"},
            error="invalid credentials",
            source="login-api",
        )
        redacted = record.to_redacted_dict()
        assert redacted["redacted"] is True
        assert "payload_summary" in redacted

    def test_empty_payload_summary(self):
        record = QuarantineRecord(payload={}, error="empty")
        summary = record._summarize_payload()
        assert summary == "(empty)"
