"""Tests for webhook payload shaping."""

import pytest
from src.webhook.shaping import (
    SensitiveFieldFilter, PayloadShapingMiddleware,
    PayloadShape, PayloadValidationError, EndpointValidator,
)


SAMPLE_PAYLOAD = {
    "event": "agent.completed",
    "agent_id": "agent-abc-123",
    "output": {"summary": "Review complete", "files_reviewed": 5},
    "internal": {
        "internal_api_key": "sk-xxxxxxxx",
        "worker_id": "worker-42",
        "heartbeat_at": "2026-05-23T06:00:00Z",
        "_locked": True,
        "_retry_count": 3,
    },
    "timestamp": "2026-05-23T06:00:00Z",
}


class TestSensitiveFieldFilter:
    def test_filters_internal_fields(self):
        result = SensitiveFieldFilter().filter(SAMPLE_PAYLOAD, PayloadShape.FULL)
        assert result["event"] == "agent.completed"
        assert "internal" not in result

    def test_filter_nested(self):
        filt = SensitiveFieldFilter()
        payload = {"meta": {"secret_token": "hidden", "visible": "ok"}}
        result = filt.filter(payload)
        assert result["meta"]["visible"] == "ok"
        assert "secret_token" not in result["meta"]

    def test_underscore_prefix_sensitive(self):
        result = SensitiveFieldFilter().filter({"_hidden": "x", "ok": "y"})
        assert "_hidden" not in result
        assert result["ok"] == "y"

    def test_list_handling(self):
        payload = {"items": [{"secret_token": "h1"}, {"name": "ok"}]}
        result = SensitiveFieldFilter().filter(payload)
        assert len(result["items"]) == 2
        assert "secret_token" not in result["items"][0]
        assert result["items"][1]["name"] == "ok"

    def test_allowlist(self):
        filt = SensitiveFieldFilter(allowlist={"worker_id"})
        payload = {"worker_id": "w-1", "internal_api_key": "hid"}
        result = filt.filter(payload)
        assert result["worker_id"] == "w-1"
        assert "internal_api_key" not in result


class TestPayloadShapingMiddleware:
    def test_shape_payload(self):
        mid = PayloadShapingMiddleware()
        result = mid.shape_payload(SAMPLE_PAYLOAD)
        assert result["event"] == "agent.completed"
        assert "internal" not in result

    def test_disabled_endpoint(self):
        mid = PayloadShapingMiddleware()
        mid.register_disabled_endpoint("ep-1")
        with pytest.raises(PayloadValidationError):
            mid.shape_payload(SAMPLE_PAYLOAD, endpoint_id="ep-1")

    def test_active_endpoint(self):
        mid = PayloadShapingMiddleware()
        result = mid.shape_payload(SAMPLE_PAYLOAD, endpoint_id="ep-2")
        assert result["event"] == "agent.completed"

    def test_endpoint_toggle(self):
        mid = PayloadShapingMiddleware()
        mid.register_disabled_endpoint("ep-3")
        assert "ep-3" in mid.disabled_endpoints
        mid.remove_disabled_endpoint("ep-3")
        assert "ep-3" not in mid.disabled_endpoints

    def test_minimal_shape(self):
        mid = PayloadShapingMiddleware(default_shape=PayloadShape.MINIMAL)
        result = mid.shape_payload(SAMPLE_PAYLOAD)
        assert result["event"] == "agent.completed"


class TestEndpointValidator:
    def test_valid_endpoint(self):
        shaping = PayloadShapingMiddleware()
        validator = EndpointValidator(shaping)
        result = validator.validate_and_register_endpoint("ep-1", "https://hook.example.com/cb")
        assert result["status"] == "active"

    def test_invalid_url(self):
        validator = EndpointValidator(PayloadShapingMiddleware())
        with pytest.raises(PayloadValidationError):
            validator.validate_and_register_endpoint("ep-1", "ftp://bad")

    def test_rotated_endpoint(self):
        shaping = PayloadShapingMiddleware()
        validator = EndpointValidator(shaping)
        result = validator.validate_and_register_endpoint("ep-rot", "https://x.com/h", is_rotated=True)
        assert result["status"] == "rotated"
        assert "ep-rot" in shaping.disabled_endpoints

    def test_delivery_to_rotated_fails(self):
        shaping = PayloadShapingMiddleware()
        validator = EndpointValidator(shaping)
        validator.validate_and_register_endpoint("ep-gone", "https://x.com/h", is_rotated=True)
        with pytest.raises(PayloadValidationError):
            validator.validate_delivery("ep-gone", SAMPLE_PAYLOAD)

    def test_delivery_to_active_succeeds(self):
        shaping = PayloadShapingMiddleware()
        validator = EndpointValidator(shaping)
        result = validator.validate_delivery("ep-active", SAMPLE_PAYLOAD)
        assert result["delivered"] is True
