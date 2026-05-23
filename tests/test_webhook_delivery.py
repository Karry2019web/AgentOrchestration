"""Tests for webhook delivery with 410 Gone handling."""

import time
import pytest
from src.webhook.delivery import (
    WebhookDeliveryService,
    EndpointStatus,
    DeliveryRecord,
    EndpointRegistration,
)


@pytest.fixture
def service():
    return WebhookDeliveryService()


class TestEndpointRegistration:
    """Tests for endpoint registration and validation."""

    def test_register_valid_endpoint(self, service):
        ep = service.register_endpoint(
            url="https://hooks.example.com/callback",
            workspace_id="ws-1",
            endpoint_id="ep-1",
        )
        assert ep.endpoint_id == "ep-1"
        assert ep.url == "https://hooks.example.com/callback"
        assert ep.workspace_id == "ws-1"
        assert ep.status == EndpointStatus.ACTIVE

    def test_register_with_auto_id(self, service):
        ep = service.register_endpoint(
            url="https://hooks.example.com/auto",
            workspace_id="ws-1",
        )
        assert ep.endpoint_id.startswith("wh_")
        assert ep.workspace_id == "ws-1"

    def test_register_rejects_empty_url(self, service):
        with pytest.raises(ValueError, match="URL must not be empty"):
            service.register_endpoint(url="", workspace_id="ws-1")

    def test_register_rejects_invalid_url(self, service):
        with pytest.raises(ValueError, match="Invalid URL"):
            service.register_endpoint(url="not-a-url", workspace_id="ws-1")

    def test_register_rejects_unsupported_scheme(self, service):
        with pytest.raises(ValueError, match="Unsupported URL scheme"):
            service.register_endpoint(url="ftp://hooks.example.com/callback", workspace_id="ws-1")

    def test_register_rejects_empty_workspace(self, service):
        with pytest.raises(ValueError, match="workspace_id must not be empty"):
            service.register_endpoint(url="https://hooks.example.com/callback", workspace_id="")

    def test_duplicate_registration_returns_existing(self, service):
        ep1 = service.register_endpoint(url="https://hooks.example.com/dup", workspace_id="ws-1", endpoint_id="ep-dup")
        ep2 = service.register_endpoint(url="https://hooks.example.com/dup", workspace_id="ws-1")
        assert ep1 is ep2


class TestDelivery:
    """Tests for webhook delivery and 410 Gone handling."""

    def test_successful_delivery(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-success")
        record = service.deliver("ep-success", {"event": "test"})
        assert record.success is True
        assert record.status_code == 200
        assert record.endpoint_id == "ep-success"

    def test_410_gone_disables_endpoint(self, service):
        service.register_endpoint(url="https://hooks.example.com/gone", workspace_id="ws-1", endpoint_id="ep-gone")
        record = service.deliver("ep-gone", {"event": "test"})
        assert record.success is False
        assert record.status_code == 410
        assert "disabled" in record.error
        ep = service.get_endpoint("ep-gone")
        assert ep.status == EndpointStatus.DISABLED_GONE

    def test_delivery_to_disabled_gone_endpoint_fails(self, service):
        service.register_endpoint(url="https://hooks.example.com/gone", workspace_id="ws-1", endpoint_id="ep-gone2")
        service.deliver("ep-gone2", {"event": "test"})
        with pytest.raises(ValueError, match="disabled"):
            service.deliver("ep-gone2", {"event": "test"})

    def test_delivery_to_unknown_endpoint_fails(self, service):
        with pytest.raises(ValueError, match="Unknown endpoint"):
            service.deliver("ep-nonexistent", {})

    def test_dry_run_does_not_send(self, service):
        service.register_endpoint(url="https://hooks.example.com/gone", workspace_id="ws-1", endpoint_id="ep-dry")
        record = service.deliver("ep-dry", {"event": "test"}, dry_run=True)
        assert record.error == "dry_run"
        assert record.success is True
        ep = service.get_endpoint("ep-dry")
        assert ep.status == EndpointStatus.ACTIVE

    def test_payload_internal_fields_filtered(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-filter")
        record = service.deliver("ep-filter", {"event": "test", "_internal": "secret", "internal_token": "abc"})
        assert record.success is True

    def test_payload_with_internal_metadata_blocked(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-block")
        with pytest.raises(ValueError, match="internal-only field"):
            service.deliver("ep-block", {"event": "test", "secret": "my-secret"})


class TestRetryBehavior:
    """Tests for idempotent retry behavior."""

    def test_retry_on_410_disables_and_stops_retries(self, service):
        service.register_endpoint(url="https://hooks.example.com/gone", workspace_id="ws-1", endpoint_id="ep-retry-gone")
        service.deliver("ep-retry-gone", {"event": "test"})
        with pytest.raises(ValueError, match="disabled"):
            service.retry_delivery("ep-retry-gone")

    def test_retry_on_transient_failure(self, service):
        service.register_endpoint(url="https://hooks.example.com/error", workspace_id="ws-1", endpoint_id="ep-retry-err")
        record = service.deliver("ep-retry-err", {"event": "test"})
        assert record.success is False

    def test_retry_exceeds_max_retries(self, service):
        service.register_endpoint(url="https://hooks.example.com/error", workspace_id="ws-1", endpoint_id="ep-retry-max")
        for _ in range(4):
            service.deliver("ep-retry-max", {"event": "test"})
        with pytest.raises(ValueError, match="exceeded max retries"):
            service.retry_delivery("ep-retry-max")


class TestWorkspaceIsolation:
    """Tests for workspace-level isolation."""

    def test_workspace_endpoints_isolated(self, service):
        service.register_endpoint(url="https://hooks.example.com/ws1", workspace_id="ws-1", endpoint_id="ep-ws1")
        service.register_endpoint(url="https://hooks.example.com/ws2", workspace_id="ws-2", endpoint_id="ep-ws2")
        assert len(service.get_workspace_endpoints("ws-1")) == 1
        assert len(service.get_workspace_endpoints("ws-2")) == 1

    def test_delivery_history_scope_by_workspace(self, service):
        service.register_endpoint(url="https://hooks.example.com/a", workspace_id="ws-1", endpoint_id="ep-ws1-a")
        service.register_endpoint(url="https://hooks.example.com/b", workspace_id="ws-2", endpoint_id="ep-ws2-b")
        service.deliver("ep-ws1-a", {"event": "t1"})
        service.deliver("ep-ws2-b", {"event": "t2"})
        assert len(service.get_workspace_delivery_history("ws-1")) == 1
        assert len(service.get_workspace_delivery_history("ws-2")) == 1

    def test_duplicate_url_across_workspaces_allowed(self, service):
        service.register_endpoint(url="https://hooks.example.com/shared", workspace_id="ws-1", endpoint_id="ep-shared-1")
        service.register_endpoint(url="https://hooks.example.com/shared", workspace_id="ws-2", endpoint_id="ep-shared-2")
        assert len(service.get_workspace_endpoints("ws-1")) == 1
        assert len(service.get_workspace_endpoints("ws-2")) == 1


class TestDeliveryRecords:
    """Tests for delivery record integrity."""

    def test_record_does_not_expose_internal_fields(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-record")
        record = service.deliver("ep-record", {"event": "test"})
        assert not hasattr(record, "payload")
        assert not hasattr(record, "metadata")
        assert record.endpoint_id == "ep-record"
        assert record.workspace_id == "ws-1"

    def test_delivery_history_redacted(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-hist")
        service.deliver("ep-hist", {"event": "test"})
        history = service.get_delivery_history("ep-hist")
        assert len(history) == 1

    def test_idempotent_records(self, service):
        service.register_endpoint(url="https://hooks.example.com/success", workspace_id="ws-1", endpoint_id="ep-idem")
        service.deliver("ep-idem", {"event": "t1"})
        service.deliver("ep-idem", {"event": "t2"})
        history = service.get_delivery_history("ep-idem")
        assert len(history) == 2


# 2026-05-23T05:30:00 initial
