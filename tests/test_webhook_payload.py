"""Tests for webhook payload shaping and delivery."""

import pytest
from src.webhook.payload import InternalFieldFilter, PayloadShapingService
from src.webhook.delivery import WebhookDeliveryService, DeliveryRecord


class TestInternalFieldFilter:
    def setup_method(self):
        self.filter = InternalFieldFilter()

    def test_filters_internal_token_field(self):
        payload = {"event_id": "evt-1", "agent_name": "test", "internal_token": "should-be-filtered"}
        result = self.filter.sanitize_payload(payload)
        assert "internal_token" not in result
        assert result["event_id"] == "evt-1"

    def test_filters_secret_and_key_fields(self):
        payload = {"event_id": "evt-1", "secret_key": "sk-123", "api_key": "ak-456", "agent_name": "test"}
        result = self.filter.sanitize_payload(payload)
        assert "secret_key" not in result
        assert "api_key" not in result
        assert result["agent_name"] == "test"

    def test_preserves_public_fields(self):
        payload = {"event_id": "evt-1", "event_type": "agent.completed", "agent_name": "worker-1", "status": "completed", "result": {"output": "ok"}}
        result = self.filter.sanitize_payload(payload)
        assert result["event_id"] == "evt-1"
        assert result["event_type"] == "agent.completed"
        assert result["status"] == "completed"

    def test_recursive_filtering_in_nested_dicts(self):
        payload = {"event_id": "evt-1", "result": {"output": "ok", "internal_token": "leaked", "runtime_env": "production"}}
        result = self.filter.sanitize_payload(payload)
        assert result["result"]["output"] == "ok"
        assert "internal_token" not in result["result"]
        assert "runtime_env" not in result["result"]

    def test_filters_internal_fields_in_lists(self):
        payload = {
            "event_id": "evt-1",
            "steps": [
                {"name": "step1", "status": "done", "internal_token": "leak1"},
                {"name": "step2", "status": "done", "private_key": "leak2"},
            ]
        }
        result = self.filter.sanitize_payload(payload)
        assert len(result["steps"]) == 2
        assert "internal_token" not in result["steps"][0]
        assert "private_key" not in result["steps"][1]
        assert result["steps"][0]["name"] == "step1"

    def test_detects_internal_field_by_convention(self):
        payload = {"event_id": "evt-1", "my_internal_id": "int-123", "auth_bearer": "bearer-xyz"}
        result = self.filter.sanitize_payload(payload)
        assert "my_internal_id" not in result
        assert "auth_bearer" not in result

    def test_non_dict_values_preserved(self):
        assert self.filter.sanitize_payload("string") == "string"
        assert self.filter.sanitize_payload(42) == 42
        assert self.filter.sanitize_payload(None) is None
        assert self.filter.sanitize_payload([1, 2, 3]) == [1, 2, 3]

    def test_custom_internal_fields(self):
        custom_filter = InternalFieldFilter(additional_internal_fields={"custom_secret", "my_internal"})
        payload = {"event_id": "evt-1", "custom_secret": "val", "my_internal": "val", "agent_name": "test"}
        result = custom_filter.sanitize_payload(payload)
        assert "custom_secret" not in result
        assert "my_internal" not in result


class TestPayloadShapingService:
    def setup_method(self):
        self.service = PayloadShapingService()

    def test_allowed_event_types_are_shaped(self):
        raw = {"event_id": "evt-1", "agent_name": "test", "status": "running"}
        result = self.service.shape_event_payload("agent.started", raw)
        assert result is not None
        assert result["event_type"] == "agent.started"

    def test_disallowed_event_types_return_none(self):
        raw = {"event_id": "evt-1", "data": "some data"}
        result = self.service.shape_event_payload("internal.debug", raw)
        assert result is None

    def test_public_fields_extracted_from_raw_payload(self):
        raw = {"event_id": "evt-1", "agent_name": "test-agent", "agent_type": "worker", "status": "completed", "run_id": "run-123", "internal_token": "sk-xxx", "runtime_env": "prod"}
        result = self.service.shape_event_payload("agent.completed", raw)
        assert result["event_id"] == "evt-1"
        assert result["agent_name"] == "test-agent"
        assert result["agent_type"] == "worker"
        assert "internal_token" not in result
        assert "runtime_env" not in result

    def test_shaped_payload_includes_timestamp(self):
        raw = {"event_id": "evt-1", "agent_name": "test"}
        result = self.service.shape_event_payload("agent.started", raw)
        assert "timestamp" in result

    def test_validate_subscription_filter_valid(self):
        valid = {"event_types": ["agent.completed", "agent.failed"], "endpoint": "https://example.com/hook"}
        assert self.service.validate_subscription_filter(valid) is True

    def test_validate_subscription_filter_invalid_event_type(self):
        invalid = {"event_types": ["agent.completed", "internal.debug"], "endpoint": "https://example.com/hook"}
        assert self.service.validate_subscription_filter(invalid) is False


class TestWebhookDeliveryService:
    def setup_method(self):
        self.service = WebhookDeliveryService(max_attempts=2, retry_delays_seconds=[0.1, 0.2])

    def test_register_and_deliver_subscription(self):
        self.service.register_subscription("sub-1", {"endpoint_url": "https://example.com/hook", "workspace_id": "ws-1", "event_types": ["agent.completed"]})
        result = self.service.deliver_event("evt-1", "sub-1", {"event_type": "agent.completed"})
        assert result.status == "delivered"
        assert result.subscription_id == "sub-1"
        assert result.response_status == 200

    def test_delivery_fails_for_unknown_subscription(self):
        result = self.service.deliver_event("evt-1", "sub-unknown", {"event_type": "agent.completed"})
        assert result.status == "failed"
        assert "not found" in (result.error_message or "").lower()

    def test_delivery_fails_for_disabled_subscription(self):
        self.service.register_subscription("sub-2", {"endpoint_url": "https://example.com/hook", "enabled": False})
        result = self.service.deliver_event("evt-1", "sub-2", {})
        assert result.status == "failed"
        assert "disabled" in (result.error_message or "").lower()

    def test_idempotent_delivery(self):
        self.service.register_subscription("sub-3", {"endpoint_url": "https://example.com/hook"})
        r1 = self.service.deliver_event("evt-1", "sub-3", {})
        r2 = self.service.deliver_event("evt-1", "sub-3", {})
        assert r1.status == "delivered"
        assert r2.status == "delivered"
        assert "Idempotent" in (r2.error_message or "")

    def test_delivery_records_tracked(self):
        self.service.register_subscription("sub-4", {"endpoint_url": "https://example.com/hook"})
        record = self.service.deliver_event("evt-1", "sub-4", {})
        fetched = self.service.get_delivery(record.delivery_id)
        assert fetched is not None
        assert fetched.status == "delivered"

    def test_workspace_isolation(self):
        self.service.register_subscription("sub-ws1", {"endpoint_url": "https://ws1.example.com/hook", "workspace_id": "ws-1"})
        self.service.register_subscription("sub-ws2", {"endpoint_url": "https://ws2.example.com/hook", "workspace_id": "ws-2"})
        self.service.deliver_event("evt-1", "sub-ws1", {})
        self.service.deliver_event("evt-2", "sub-ws2", {})
        ws1_deliveries = self.service.workspace_deliveries("ws-1")
        ws2_deliveries = self.service.workspace_deliveries("ws-2")
        assert len(ws1_deliveries) == 1
        assert len(ws2_deliveries) == 1

    def test_get_deliveries_for_subscription(self):
        self.service.register_subscription("sub-5", {"endpoint_url": "https://example.com/hook"})
        self.service.deliver_event("evt-1", "sub-5", {})
        self.service.deliver_event("evt-2", "sub-5", {})
        records = self.service.get_deliveries_for_subscription("sub-5")
        assert len(records) == 2
