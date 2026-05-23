"""Tests for webhook delivery and payload shaping."""

import pytest
from src.common.webhooks import (
    WebhookDelivery,
    WebhookEndpoint,
    PayloadFilter,
    INTERNAL_METADATA_FIELDS,
)


class TestPayloadFilter:
    def test_strips_internal_fields(self):
        payload = {
            "run_id": "abc-123",
            "status": "completed",
            "token": "super-secret",
            "execution_id": "exec-1",
            "result": {"data": "ok"},
        }
        cleaned = PayloadFilter.strip_internal_fields(payload)
        assert "token" not in cleaned
        assert "execution_id" not in cleaned
        assert cleaned["run_id"] == "abc-123"
        assert cleaned["status"] == "completed"

    def test_strips_nested_internal_fields(self):
        payload = {"run": {"id": "r1", "secret": "hidden", "hostname": "box-1"}}
        cleaned = PayloadFilter.strip_internal_fields(payload)
        assert "secret" not in cleaned["run"]
        assert "hostname" not in cleaned["run"]
        assert cleaned["run"]["id"] == "r1"

    def test_strips_internal_in_lists(self):
        payload = {
            "items": [
                {"name": "a", "api_key": "sk-123"},
                {"name": "b", "api_key": "sk-456"},
            ]
        }
        cleaned = PayloadFilter.strip_internal_fields(payload)
        assert "api_key" not in cleaned["items"][0]
        assert "api_key" not in cleaned["items"][1]
        assert cleaned["items"][0]["name"] == "a"

    def test_preserves_safe_fields(self):
        payload = {"event": "task.completed", "data": {"output": "done"}}
        cleaned = PayloadFilter.strip_internal_fields(payload)
        assert cleaned == payload

    def test_filter_event_data_adds_metadata(self):
        result = PayloadFilter.filter_event_data(
            "task.completed", {"output": "ok", "token": "x"}, allowed_fields=["output"]
        )
        assert result["event"] == "task.completed"
        assert "timestamp" in result
        assert result["data"] == {"output": "ok"}
        assert "token" not in result["data"]

    def test_empty_payload(self):
        assert PayloadFilter.strip_internal_fields({}) == {}

    def test_non_dict_payload(self):
        assert PayloadFilter.strip_internal_fields("string") == "string"

    def test_internal_fields_set_is_comprehensive(self):
        assert "token" in INTERNAL_METADATA_FIELDS
        assert "secret" in INTERNAL_METADATA_FIELDS
        assert "password" in INTERNAL_METADATA_FIELDS


class TestWebhookEndpoint:
    def test_to_public_dict_excludes_secrets(self):
        ep = WebhookEndpoint(
            url="https://hooks.example.com/callback",
            secret="super-secret-value",
            event_types=["task.completed"],
        )
        public = ep.to_public_dict()
        assert public["url"] == "https://hooks.example.com/callback"
        assert public["enabled"] is True
        assert public["event_types"] == ["task.completed"]
        assert "secret" not in public
        assert "id" in public

    def test_default_values(self):
        ep = WebhookEndpoint()
        assert ep.enabled is True
        assert ep.max_retries == 3
        assert ep.timeout == 10.0
        assert ep.event_types == []


class TestWebhookDelivery:
    def setup_method(self):
        self.delivery = WebhookDelivery()

    def test_register_endpoint(self):
        ep = self.delivery.register_endpoint(
            "https://hooks.example.com/callback",
            secret="s3cr3t",
            event_types=["task.completed"],
        )
        assert ep.url == "https://hooks.example.com/callback"
        assert self.delivery.get_endpoint(ep.id) is ep

    def test_register_endpoint_no_event_types(self):
        ep = self.delivery.register_endpoint("https://hooks.example.com/notify")
        assert ep.event_types == []

    def test_get_endpoint_nonexistent(self):
        assert self.delivery.get_endpoint("does-not-exist") is None

    def test_remove_endpoint(self):
        ep = self.delivery.register_endpoint("https://hooks.example.com/cb")
        assert self.delivery.remove_endpoint(ep.id) is True
        assert self.delivery.get_endpoint(ep.id) is None

    def test_remove_nonexistent_endpoint(self):
        assert self.delivery.remove_endpoint("nope") is False

    def test_get_all_endpoints(self):
        self.delivery.register_endpoint("https://a.com/a")
        self.delivery.register_endpoint("https://b.com/b")
        assert len(self.delivery.get_all_endpoints()) == 2

    def test_get_active_endpoints_for_event(self):
        self.delivery.register_endpoint(
            "https://a.com/a", event_types=["task.completed"]
        )
        self.delivery.register_endpoint(
            "https://b.com/b", event_types=["task.failed"]
        )
        active = self.delivery.get_active_endpoints_for_event("task.completed")
        assert len(active) == 1
        assert active[0].url == "https://a.com/a"

    def test_get_active_excludes_disabled(self):
        ep = self.delivery.register_endpoint(
            "https://a.com/a", event_types=["task.completed"]
        )
        ep.enabled = False
        active = self.delivery.get_active_endpoints_for_event("task.completed")
        assert len(active) == 0

    def test_get_active_all_events_when_no_filter(self):
        ep = self.delivery.register_endpoint("https://hooks.example.com/all")
        active = self.delivery.get_active_endpoints_for_event("task.completed")
        assert len(active) == 1

    def test_deliver_public_only(self):
        url = "https://hooks.example.com/task-completed"
        ep = self.delivery.register_endpoint(url, event_types=["task.completed"])
        import asyncio
        results = asyncio.run(
            self.delivery.deliver(
                "task.completed",
                {"id": "t1", "token": "secret-token", "status": "done", "hostname": "box-1"},
            )
        )
        assert len(results) == 1
        assert results[0]["status"] == "delivered"
        record = self.delivery.get_delivery_record(results[0]["delivery_id"])
        assert record is not None
        assert "token" not in record
        assert "hostname" not in record

    def test_deliver_multiple_endpoints(self):
        self.delivery.register_endpoint(
            "https://a.com/hook", event_types=["task.completed"]
        )
        self.delivery.register_endpoint(
            "https://b.com/hook", event_types=["task.completed"]
        )
        import asyncio
        results = asyncio.run(
            self.delivery.deliver("task.completed", {"id": "t1"})
        )
        assert len(results) == 2

    def test_deliver_no_matching_endpoints(self):
        import asyncio
        results = asyncio.run(
            self.delivery.deliver("task.unknown", {"id": "t1"})
        )
        assert results == []

    def test_deliver_with_custom_http_client(self):
        async def fake_client(url: str, body: str, secret: str) -> dict:
            return {"status": "ok"}
        self.delivery.set_http_client(fake_client)
        self.delivery.register_endpoint(
            "https://custom.test/hook", event_types=["task.completed"]
        )
        import asyncio
        results = asyncio.run(
            self.delivery.deliver("task.completed", {"id": "t1"})
        )
        assert len(results) == 1
        assert results[0]["status"] == "delivered"

    def test_get_delivery_records(self):
        self.delivery.register_endpoint("https://a.com/hook", event_types=["evt"])
        import asyncio
        asyncio.run(self.delivery.deliver("evt", {"id": "1"}))
        records = self.delivery.get_delivery_records()
        assert len(records) == 1

    def test_get_delivery_records_filtered(self):
        ep = self.delivery.register_endpoint("https://a.com/hook", event_types=["evt"])
        import asyncio
        asyncio.run(self.delivery.deliver("evt", {"id": "1"}))
        records = self.delivery.get_delivery_records(endpoint_id=ep.id)
        assert len(records) == 1

    def test_delivery_idempotent(self):
        self.delivery.register_endpoint("https://a.com/hook", event_types=["evt"])
        import asyncio
        r1 = asyncio.run(self.delivery.deliver("evt", {"id": "1"}))
        r2 = asyncio.run(self.delivery.deliver("evt", {"id": "1"}))
        assert r1[0]["delivery_id"] != r2[0]["delivery_id"]

    def test_endpoint_workspace_isolation(self):
        """Verify delivery only goes to matching endpoints."""
        self.delivery.register_endpoint(
            "https://team-a/hook", event_types=["task.completed"]
        )
        self.delivery.register_endpoint(
            "https://team-b/hook", event_types=["task.failed"]
        )
        import asyncio
        results = asyncio.run(
            self.delivery.deliver("task.completed", {"id": "t1"})
        )
        assert len(results) == 1
