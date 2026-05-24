"""Tests for webhook delivery audit store."""

import pytest
from src.webhook import DeliveryAuditStore, DeliveryRejected


class TestDeliveryAuditStore:
    def setup_method(self):
        self.store = DeliveryAuditStore()
        self.store.register_endpoint("ws-1", "ep-1", "https://hooks.example.com/callback")

    def test_records_valid_delivery(self):
        record = self.store.record_delivery(
            "ws-1", "ep-1", "del-1", "delivered",
            {"event": "run.completed", "data": {"ok": True}},
        )
        assert record.delivery_id == "del-1"
        assert record.status == "delivered"
        assert record.sequence == 1
        assert record.payload == {"event": "run.completed", "data": {"ok": True}}

    def test_rejects_unregistered_endpoint(self):
        with pytest.raises(DeliveryRejected, match="not registered"):
            self.store.record_delivery("ws-1", "ep-unknown", "del-1", "delivered", {})

    def test_rejects_disabled_endpoint(self):
        self.store.register_endpoint("ws-1", "ep-disabled", "https://hook.example.com", enabled=False)
        with pytest.raises(DeliveryRejected, match="disabled"):
            self.store.record_delivery("ws-1", "ep-disabled", "del-1", "delivered", {})

    def test_rejects_non_dict_payload(self):
        with pytest.raises(DeliveryRejected, match="payload must be a dict"):
            self.store.record_delivery("ws-1", "ep-1", "del-1", "delivered", "bad")

    def test_stale_delivery_rejected(self):
        r1 = self.store.record_delivery("ws-1", "ep-1", "del-2", "delivered", {"x": 1})
        seq1 = r1.sequence
        self.store._sequence = seq1 - 1
        with pytest.raises(DeliveryRejected, match="stale delivery"):
            self.store.record_delivery("ws-1", "ep-1", "del-2", "delivered", {"x": 2})

    def test_removes_internal_fields(self):
        record = self.store.record_delivery(
            "ws-1", "ep-1", "del-3", "delivered",
            {"event": "ok", "internal_run_id": "secret-123", "token": "abc"},
        )
        assert "internal_run_id" not in record.payload
        assert "token" not in record.payload
        assert record.payload["event"] == "ok"

    def test_get_last_delivery_returns_none(self):
        assert self.store.get_last_delivery("ws-1", "ep-1", "nonexistent") is None

    def test_get_last_delivery_returns_record(self):
        self.store.record_delivery("ws-1", "ep-1", "del-4", "failed", {"error": "timeout"})
        record = self.store.get_last_delivery("ws-1", "ep-1", "del-4")
        assert record is not None
        assert record.status == "failed"

    def test_workspace_isolation(self):
        self.store.register_endpoint("ws-2", "ep-1", "https://other.hook/cb")
        self.store.record_delivery("ws-1", "ep-1", "del-5", "ok", {})
        self.store.record_delivery("ws-2", "ep-1", "del-5", "ok", {})
        r1 = self.store.get_last_delivery("ws-1", "ep-1", "del-5")
        r2 = self.store.get_last_delivery("ws-2", "ep-1", "del-5")
        assert r1 is not None
        assert r2 is not None

    def test_remove_endpoint(self):
        self.store.remove_endpoint("ws-1", "ep-1")
        with pytest.raises(DeliveryRejected, match="not registered"):
            self.store.record_delivery("ws-1", "ep-1", "del-6", "delivered", {})
