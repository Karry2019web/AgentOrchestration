"""Tests for webhook idempotency keys."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.api.webhook import IdempotencyStore, EndpointValidator, WebhookDeliverer


class TestIdempotencyStore:
    def setup_method(self):
        self.store = IdempotencyStore()

    def test_get_nonexistent(self):
        assert self.store.get("nonexistent") is None

    def test_set_and_get(self):
        self.store.set("key1", "delivered")
        result = self.store.get("key1")
        assert result["status"] == "delivered"
        assert "stored_at" in result

    def test_exists(self):
        self.store.set("key2", "pending")
        assert self.store.exists("key2") is True
        assert self.store.exists("missing") is False

    def test_cleanup_expired(self):
        store = IdempotencyStore(ttl=-1)
        store.set("expired", "done")
        cleaned = store.cleanup()
        assert cleaned >= 1
        assert store.get("expired") is None


class TestEndpointValidator:
    def setup_method(self):
        self.validator = EndpointValidator()

    def test_valid_https(self):
        result = self.validator.validate("https://example.com/webhook")
        assert result["valid"] is True

    def test_empty_url(self):
        result = self.validator.validate("")
        assert result["valid"] is False
        assert result["reason"] == "empty_url"

    def test_non_https_rejected(self):
        result = self.validator.validate("http://insecure.com/hook")
        assert result["valid"] is False
        assert result["reason"] == "non_https_url"

    def test_localhost_blocked(self):
        result = self.validator.validate("https://localhost:8080/hook")
        assert result["valid"] is False
        assert result["reason"] == "blocked_host"


class TestWebhookDeliverer:
    def setup_method(self):
        self.deliverer = WebhookDeliverer()

    def test_valid_delivery(self):
        result = self.deliverer.deliver(
            event_id="evt-001",
            destination="https://example.com/hook",
            event_type="task.complete",
            payload={"task_id": "t-1"},
        )
        assert result["status"] == "delivered"
        assert "idempotency_key" in result

    def test_duplicate_detection(self):
        result1 = self.deliverer.deliver(
            "evt-002", "https://example.com/hook", "task.complete", {"id": 1}
        )
        assert result1["status"] == "delivered"

        result2 = self.deliverer.deliver(
            "evt-002", "https://example.com/hook", "task.complete", {"id": 1}
        )
        assert result2["status"] == "duplicate"
        assert result2["original_status"] == "delivered"

    def test_rejected_endpoint(self):
        result = self.deliverer.deliver(
            "evt-003", "", "task.start", {}
        )
        assert result["status"] == "rejected"

    def test_delivery_log(self):
        self.deliverer.deliver(
            "evt-004", "https://valid.com/hook", "task.fail", {"error": "err"}
        )
        log = self.deliverer.get_delivery_log()
        assert len(log) >= 1
        assert log[-1]["event_id"] == "evt-004"

    def test_get_delivery_by_key(self):
        result = self.deliverer.deliver(
            "evt-005", "https://valid.com/hook", "system.health", {}
        )
        key = result["idempotency_key"]
        record = self.deliverer.get_delivery(key)
        assert record is not None
        assert record["event_id"] == "evt-005"
