"""Tests for webhook idempotency delivery."""

import asyncio
import hashlib
import json
import time

import pytest

from src.api.webhook import (
    IdempotencyStore,
    EndpointValidator,
    WebhookDeliverer,
    WebhookEvent,
    DeliveryRecord,
    WebhookDeliveryError,
    EndpointValidationError,
    reset_deliverer,
)


class TestIdempotencyStore:
    def test_set_and_get(self):
        store = IdempotencyStore(ttl_seconds=3600)
        store.set("key1", "delivered")
        result = store.get("key1")
        assert result is not None
        assert result["status"] == "delivered"

    def test_get_nonexistent(self):
        store = IdempotencyStore()
        assert store.get("nonexistent") is None

    def test_exists(self):
        store = IdempotencyStore()
        store.set("key1", "delivered")
        assert store.exists("key1") is True
        assert store.exists("nokey") is False

    def test_ttl_expiry(self):
        store = IdempotencyStore(ttl_seconds=0)
        store.set("key1", "delivered")
        assert store.get("key1") is None
        assert store.exists("key1") is False

    def test_cleanup(self):
        store = IdempotencyStore(ttl_seconds=0)
        store.set("a", "delivered")
        store.set("b", "failed")
        cleaned = store.cleanup()
        assert cleaned == 2
        assert store.get("a") is None

    def test_set_duplicate_key(self):
        store = IdempotencyStore()
        store.set("key1", "delivered")
        store.set("key1", "failed")
        result = store.get("key1")
        assert result["status"] == "failed"

    def test_idempotent_get_after_set(self):
        store = IdempotencyStore()
        store.set("key1", "delivered")
        r1 = store.get("key1")
        r2 = store.get("key1")
        assert r1["status"] == r2["status"]


class TestEndpointValidator:
    def test_valid_https(self):
        v = EndpointValidator()
        is_valid, err = v.validate("https://example.com/webhook")
        assert is_valid is True
        assert err is None

    def test_rejects_http(self):
        v = EndpointValidator()
        is_valid, err = v.validate("http://example.com/webhook")
        assert is_valid is False
        assert "https" in err

    def test_rejects_empty(self):
        v = EndpointValidator()
        is_valid, err = v.validate("")
        assert is_valid is False

    def test_rejects_none(self):
        v = EndpointValidator()
        is_valid, err = v.validate(None)
        assert is_valid is False

    def test_blocked_host(self):
        v = EndpointValidator()
        v.block_host("evil.example.com")
        is_valid, err = v.validate("https://evil.example.com/hook")
        assert is_valid is False
        assert "blocked" in err

    def test_allowed_host_not_blocked(self):
        v = EndpointValidator()
        v.block_host("evil.example.com")
        is_valid, err = v.validate("https://good.example.com/hook")
        assert is_valid is True


class TestWebhookDeliverer:
    @pytest.mark.asyncio
    async def test_deliver_rejects_invalid_endpoint(self):
        deliverer = WebhookDeliverer()
        event = WebhookEvent(event_id="evt-1", event_type="test", payload={"msg": "hello"})
        with pytest.raises(EndpointValidationError):
            await deliverer.deliver(event, "http://insecure.com", "wh-1")

    @pytest.mark.asyncio
    async def test_deliver_rejects_empty_url(self):
        deliverer = WebhookDeliverer()
        event = WebhookEvent(event_id="evt-2", event_type="test", payload={})
        with pytest.raises(EndpointValidationError):
            await deliverer.deliver(event, "", "wh-1")

    @pytest.mark.asyncio
    async def test_duplicate_detection(self):
        store = IdempotencyStore()
        deliverer = WebhookDeliverer(idempotency_store=store)
        event = WebhookEvent(event_id="evt-3", event_type="test", payload={"n": 1})
        store.set("dupe-key", "delivered")
        result = await deliverer.deliver(event, "https://example.com/hook", "wh-1", idempotency_key="dupe-key")
        assert result["status"] == "duplicate"
        assert result["original_status"] == "delivered"

    @pytest.mark.asyncio
    async def test_duplicate_via_generated_key(self):
        store = IdempotencyStore()
        deliverer = WebhookDeliverer(idempotency_store=store)
        event = WebhookEvent(event_id="evt-4", event_type="test", payload={"n": 2})
        key = hashlib.sha256(f"{event.event_id}:https://hook.example.com/h:test".encode()).hexdigest()
        store.set(key, "delivered")
        result = await deliverer.deliver(event, "https://hook.example.com/h", "wh-1")
        assert result["status"] == "duplicate"

    def test_count_starts_zero(self):
        d = WebhookDeliverer()
        assert d.count() == 0

    def test_lookup_nonexistent(self):
        d = WebhookDeliverer()
        assert d.lookup("nokey") is None

    @pytest.mark.asyncio
    async def test_delivery_log_rejected_endpoint(self):
        d = WebhookDeliverer()
        event = WebhookEvent(event_id="evt-5", event_type="test", payload={})
        with pytest.raises(EndpointValidationError):
            await d.deliver(event, "http://bad.com", "wh-1")
        assert d.count() == 1
        assert d.records[0]["status"] == "rejected"

    def test_reset_deliverer(self):
        store = IdempotencyStore()
        d = WebhookDeliverer(idempotency_store=store)
        assert d is not None
        reset_deliverer()
        d2 = WebhookDeliverer(idempotency_store=IdempotencyStore())
        assert d2 is not None

    def test_backoff_increases(self):
        d = WebhookDeliverer()
        assert d._backoff(1) <= 2.0
        assert d._backoff(2) > d._backoff(1)
        assert d._backoff(5) <= 30.0


# 2026-05-22T02:02:38 update
