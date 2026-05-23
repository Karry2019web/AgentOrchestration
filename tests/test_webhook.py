"""Tests for the webhook idempotency and delivery module."""

import hashlib
import json
import time
from unittest.mock import patch, MagicMock

import pytest
from src.webhook import (
    WebhookDeliveryService,
    WebhookEndpoint,
    DeliveryRecord,
    DeliveryStatus,
    EndpointStatus,
    IdempotencyStore,
)


class TestIdempotencyStore:
    def test_store_and_retrieve(self):
        store = IdempotencyStore(ttl_seconds=3600)
        record = DeliveryRecord(
            delivery_id="del-1",
            idempotency_key="key-1",
            endpoint_id="ep-1",
            event_type="test.event",
            payload_hash="abc123",
            status=DeliveryStatus.DELIVERED,
        )
        store.put(record)
        retrieved = store.get("key-1")
        assert retrieved is not None
        assert retrieved.idempotency_key == "key-1"
        assert retrieved.status == DeliveryStatus.DELIVERED

    def test_expired_record_returns_none(self):
        store = IdempotencyStore(ttl_seconds=0)
        record = DeliveryRecord(
            delivery_id="del-2",
            idempotency_key="key-2",
            endpoint_id="ep-1",
            event_type="test.event",
            payload_hash="abc123",
            status=DeliveryStatus.DELIVERED,
        )
        store.put(record)
        time.sleep(0.01)
        assert store.get("key-2") is None

    def test_nonexistent_key(self):
        store = IdempotencyStore()
        assert store.get("nonexistent") is None

    def test_cleanup_expired(self):
        store = IdempotencyStore(ttl_seconds=0)
        for i in range(3):
            record = DeliveryRecord(
                delivery_id=f"del-{i}",
                idempotency_key=f"key-{i}",
                endpoint_id="ep-1",
                event_type="test.event",
                payload_hash="abc",
                status=DeliveryStatus.DELIVERED,
            )
            store.put(record)
        time.sleep(0.01)
        cleaned = store.cleanup()
        assert cleaned == 3


class TestWebhookDeliveryService:
    def setup_method(self):
        self.service = WebhookDeliveryService(idempotency_ttl=3600)
        self.endpoint_id = self.service.register_endpoint(
            url="https://example.com/webhook",
            secret="test-secret-123",
            events=["order.created", "order.updated"],
            workspace_id="ws-1",
        )

    def test_register_endpoint(self):
        assert self.endpoint_id is not None
        endpoint = self.service.get_endpoint(self.endpoint_id)
        assert endpoint.url == "https://example.com/webhook"
        assert endpoint.status == EndpointStatus.ACTIVE
        assert endpoint.workspace_id == "ws-1"

    def test_register_endpoint_with_wildcard(self):
        eid = self.service.register_endpoint(
            url="https://example.com/all-events",
            secret="secret",
            events=["*"],
            workspace_id="ws-2",
        )
        endpoint = self.service.get_endpoint(eid)
        assert "*" in endpoint.events

    def test_generate_idempotency_key(self):
        key1 = WebhookDeliveryService.generate_idempotency_key(
            "order.created", {"id": 1, "amount": 100}
        )
        key2 = WebhookDeliveryService.generate_idempotency_key(
            "order.created", {"id": 1, "amount": 100}
        )
        key3 = WebhookDeliveryService.generate_idempotency_key(
            "order.created", {"id": 2, "amount": 200}
        )
        assert key1 == key2
        assert key1 != key3

    def test_sign_and_verify_payload(self):
        payload = {"event": "test", "data": "value"}
        secret = "my-secret"
        signature = WebhookDeliveryService.sign_payload(payload, secret)
        assert WebhookDeliveryService.verify_signature(payload, secret, signature)
        assert not WebhookDeliveryService.verify_signature(
            payload, "wrong-secret", signature
        )

    @patch("src.webhook.httpx.Client")
    def test_successful_delivery(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_client.post.return_value = mock_response

        record = self.service.deliver(
            self.endpoint_id,
            "order.created",
            {"order_id": "ord-1", "amount": 99.99},
        )

        assert record.status == DeliveryStatus.DELIVERED
        assert record.status_code == 200
        assert record.endpoint_id == self.endpoint_id

    @patch("src.webhook.httpx.Client")
    def test_idempotent_delivery_blocks_duplicate(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_client.post.return_value = mock_response

        payload = {"order_id": "ord-dup", "amount": 50.0}

        first = self.service.deliver(
            self.endpoint_id, "order.created", payload
        )
        assert first.status == DeliveryStatus.DELIVERED

        second = self.service.deliver(
            self.endpoint_id, "order.created", payload
        )
        assert second.status == DeliveryStatus.DUPLICATE
        # Only one actual HTTP request was made
        assert mock_client.post.call_count == 1

    @patch("src.webhook.httpx.Client")
    def test_different_payloads_are_not_duplicates(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_client.post.return_value = mock_response

        first = self.service.deliver(
            self.endpoint_id, "order.created", {"id": 1}
        )
        second = self.service.deliver(
            self.endpoint_id, "order.created", {"id": 2}
        )

        assert first.status == DeliveryStatus.DELIVERED
        assert second.status == DeliveryStatus.DELIVERED
        assert mock_client.post.call_count == 2

    def test_delivery_to_disabled_endpoint_raises_error(self):
        self.service.disable_endpoint(self.endpoint_id)

        with pytest.raises(ValueError, match="disabled"):
            self.service.deliver(
                self.endpoint_id, "order.created", {"id": 1}
            )

    def test_delivery_to_nonexistent_endpoint_raises_error(self):
        with pytest.raises(ValueError, match="Endpoint not found"):
            self.service.deliver(
                "nonexistent-endpoint", "order.created", {"id": 1}
            )

    @patch("src.webhook.httpx.Client")
    def test_410_gone_disables_endpoint(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 410
        mock_client.post.return_value = mock_response

        record = self.service.deliver(
            self.endpoint_id, "order.created", {"id": 1}
        )

        assert record.status == DeliveryStatus.FAILED
        endpoint = self.service.get_endpoint(self.endpoint_id)
        assert endpoint.status == EndpointStatus.GONE

    @patch("src.webhook.httpx.Client")
    def test_connection_error_retries(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        from httpx import RequestError

        mock_client.post.side_effect = RequestError("Connection refused")

        record = self.service.deliver(
            self.endpoint_id, "order.created", {"id": 1}
        )

        assert record.status == DeliveryStatus.RETRYING
        endpoint = self.service.get_endpoint(self.endpoint_id)
        assert endpoint.retry_count == 1

    def test_rotate_secret(self):
        result = self.service.rotate_secret(self.endpoint_id, "new-secret-456")
        assert result
        endpoint = self.service.get_endpoint(self.endpoint_id)
        assert endpoint.secret == "new-secret-456"
        assert endpoint.status == EndpointStatus.ROTATED

    def test_list_endpoints_by_workspace(self):
        eid2 = self.service.register_endpoint(
            url="https://other.com/webhook",
            secret="sec",
            events=["*"],
            workspace_id="ws-2",
        )
        ws1_endpoints = self.service.list_endpoints(workspace_id="ws-1")
        assert len(ws1_endpoints) == 1
        assert ws1_endpoints[0].endpoint_id == self.endpoint_id

        ws2_endpoints = self.service.list_endpoints(workspace_id="ws-2")
        assert len(ws2_endpoints) == 1
        assert ws2_endpoints[0].endpoint_id == eid2

    @patch("src.webhook.httpx.Client")
    def test_deliver_to_workspace(self, mock_client_class):
        mock_client = MagicMock()
        mock_client_class.return_value.__enter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"ok": true}'
        mock_client.post.return_value = mock_response

        self.service.register_endpoint(
            url="https://ws-example.com/webhook",
            secret="sec",
            events=["order.created"],
            workspace_id="ws-1",
        )

        results = self.service.deliver_to_workspace(
            "ws-1", "order.created", {"id": 1}
        )

        assert len(results) == 2
        assert all(r.status == DeliveryStatus.DELIVERED for r in results)

    def test_explicit_idempotency_key(self):
        custom_key = "my-custom-idempotency-key-123"
        with patch("src.webhook.httpx.Client") as mock_class:
            mock_client = MagicMock()
            mock_class.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = "ok"
            mock_client.post.return_value = mock_resp

            record = self.service.deliver(
                self.endpoint_id,
                "test.event",
                {"data": "value"},
                idempotency_key=custom_key,
            )
            assert record.idempotency_key == custom_key

    def test_delivery_record_has_expires_at(self):
        record = DeliveryRecord(
            delivery_id="test",
            idempotency_key="key",
            endpoint_id="ep",
            event_type="evt",
            payload_hash="hash",
            status=DeliveryStatus.DELIVERED,
        )
        assert record.expires_at > record.created_at
        assert record.expires_at - record.created_at == pytest.approx(86400, rel=0.1)
