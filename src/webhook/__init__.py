"""Webhook delivery module with idempotency key support."""

import hashlib
import hmac
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class DeliveryStatus(Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    DUPLICATE = "duplicate"
    RETRYING = "retrying"


class EndpointStatus(Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ROTATED = "rotated"
    GONE = "gone"


@dataclass
class WebhookEndpoint:
    """A registered webhook endpoint."""
    endpoint_id: str
    url: str
    secret: str
    events: List[str]
    status: EndpointStatus = EndpointStatus.ACTIVE
    workspace_id: str = "default"
    created_at: float = field(default_factory=time.time)
    retry_count: int = 0
    last_delivery_at: Optional[float] = None


@dataclass
class DeliveryRecord:
    """Record of a webhook delivery attempt."""
    delivery_id: str
    idempotency_key: str
    endpoint_id: str
    event_type: str
    payload_hash: str
    status: DeliveryStatus
    status_code: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + 86400)
    response_body: Optional[str] = None


class IdempotencyStore:
    """In-memory store for idempotency keys with TTL."""

    def __init__(self, ttl_seconds: int = 86400):
        self._store: Dict[str, DeliveryRecord] = {}
        self._ttl = ttl_seconds

    def get(self, idempotency_key: str) -> Optional[DeliveryRecord]:
        record = self._store.get(idempotency_key)
        if record and time.time() > record.expires_at:
            self._store.pop(idempotency_key, None)
            return None
        return record

    def put(self, record: DeliveryRecord) -> None:
        record.expires_at = time.time() + self._ttl
        self._store[record.idempotency_key] = record

    def cleanup(self) -> int:
        now = time.time()
        expired = [k for k, v in self._store.items() if now > v.expires_at]
        for k in expired:
            del self._store[k]
        return len(expired)


class WebhookDeliveryService:
    """Handles webhook delivery with idempotency key deduplication."""

    def __init__(
        self,
        idempotency_ttl: int = 86400,
        max_retries: int = 3,
        retry_delay: float = 60.0,
    ):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._idempotency = IdempotencyStore(ttl_seconds=idempotency_ttl)
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._workspace_endpoints: Dict[str, List[str]] = {}

    def register_endpoint(
        self,
        url: str,
        secret: str,
        events: List[str],
        workspace_id: str = "default",
    ) -> str:
        """Register a new webhook endpoint."""
        endpoint_id = str(uuid.uuid4())
        endpoint = WebhookEndpoint(
            endpoint_id=endpoint_id,
            url=url,
            secret=secret,
            events=events,
            workspace_id=workspace_id,
        )
        self._endpoints[endpoint_id] = endpoint
        if workspace_id not in self._workspace_endpoints:
            self._workspace_endpoints[workspace_id] = []
        self._workspace_endpoints[workspace_id].append(endpoint_id)
        logger.info(f"Registered endpoint {endpoint_id} for workspace {workspace_id}")
        return endpoint_id

    def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        return self._endpoints.get(endpoint_id)

    def disable_endpoint(self, endpoint_id: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint.status = EndpointStatus.DISABLED
        logger.warning(f"Endpoint {endpoint_id} disabled")
        return True

    def rotate_secret(self, endpoint_id: str, new_secret: str) -> bool:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            return False
        endpoint.secret = new_secret
        endpoint.status = EndpointStatus.ROTATED
        logger.info(f"Endpoint {endpoint_id} secret rotated")
        return True

    def list_endpoints(self, workspace_id: Optional[str] = None) -> List[WebhookEndpoint]:
        if workspace_id:
            ids = self._workspace_endpoints.get(workspace_id, [])
            return [self._endpoints[eid] for eid in ids if eid in self._endpoints]
        return list(self._endpoints.values())

    @staticmethod
    def generate_idempotency_key(event_type: str, payload: Dict) -> str:
        raw = f"{event_type}:{json.dumps(payload, sort_keys=True)}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def generate_nonce_idempotency_key() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def sign_payload(payload: Dict, secret: str) -> str:
        payload_bytes = json.dumps(payload, sort_keys=True).encode()
        return hmac.new(secret.encode(), payload_bytes, hashlib.sha256).hexdigest()

    @staticmethod
    def verify_signature(payload: Dict, secret: str, signature: str) -> bool:
        expected = WebhookDeliveryService.sign_payload(payload, secret)
        return hmac.compare_digest(expected, signature)

    def deliver(
        self,
        endpoint_id: str,
        event_type: str,
        payload: Dict,
        idempotency_key: Optional[str] = None,
    ) -> DeliveryRecord:
        endpoint = self._endpoints.get(endpoint_id)
        if not endpoint:
            raise ValueError(f"Endpoint not found: {endpoint_id}")

        if endpoint.status in (EndpointStatus.DISABLED, EndpointStatus.GONE):
            raise ValueError(f"Endpoint {endpoint_id} is {endpoint.status.value}")

        if idempotency_key is None:
            idempotency_key = self.generate_idempotency_key(event_type, payload)

        existing = self._idempotency.get(idempotency_key)
        if existing and existing.status == DeliveryStatus.DELIVERED:
            logger.info(
                f"Duplicate delivery blocked for idempotency_key={idempotency_key[:16]}..., "
                f"original delivery_id={existing.delivery_id}"
            )
            return DeliveryRecord(
                delivery_id=str(uuid.uuid4()),
                idempotency_key=idempotency_key,
                endpoint_id=endpoint_id,
                event_type=event_type,
                payload_hash=hashlib.sha256(
                    json.dumps(payload, sort_keys=True).encode()
                ).hexdigest(),
                status=DeliveryStatus.DUPLICATE,
                status_code=existing.status_code,
            )

        signature = self.sign_payload(payload, endpoint.secret)
        headers = {
            "Content-Type": "application/json",
            "X-Webhook-ID": endpoint_id,
            "X-Idempotency-Key": idempotency_key,
            "X-Webhook-Signature": signature,
            "X-Webhook-Event": event_type,
            "X-Webhook-Delivery-Id": str(uuid.uuid4()),
        }

        delivery_id = str(uuid.uuid4())
        status_code = None
        response_body = None
        status = DeliveryStatus.FAILED

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(endpoint.url, json=payload, headers=headers)
                status_code = resp.status_code
                response_body = resp.text[:1000] if resp.text else None

                if 200 <= resp.status_code < 300:
                    status = DeliveryStatus.DELIVERED
                    logger.info(
                        f"Delivered event {event_type} to {endpoint.url} "
                        f"(status={resp.status_code})"
                    )
                elif resp.status_code == 410:
                    self.disable_endpoint(endpoint_id)
                    endpoint.status = EndpointStatus.GONE
                    logger.warning(f"Endpoint {endpoint_id} returned 410 Gone")
                    status = DeliveryStatus.FAILED
                else:
                    endpoint.retry_count += 1
                    if endpoint.retry_count <= self._max_retries:
                        status = DeliveryStatus.RETRYING
                    else:
                        status = DeliveryStatus.FAILED
        except httpx.RequestError as e:
            endpoint.retry_count += 1
            if endpoint.retry_count <= self._max_retries:
                status = DeliveryStatus.RETRYING
            else:
                status = DeliveryStatus.FAILED
            response_body = str(e)

        payload_hash = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        record = DeliveryRecord(
            delivery_id=delivery_id,
            idempotency_key=idempotency_key,
            endpoint_id=endpoint_id,
            event_type=event_type,
            payload_hash=payload_hash,
            status=status,
            status_code=status_code,
            response_body=response_body,
        )

        if status == DeliveryStatus.DELIVERED:
            self._idempotency.put(record)

        endpoint.last_delivery_at = time.time()
        return record

    def deliver_to_workspace(
        self,
        workspace_id: str,
        event_type: str,
        payload: Dict,
    ) -> List[DeliveryRecord]:
        results = []
        endpoint_ids = self._workspace_endpoints.get(workspace_id, [])

        for eid in endpoint_ids:
            endpoint = self._endpoints.get(eid)
            if endpoint and endpoint.status == EndpointStatus.ACTIVE:
                if event_type in endpoint.events or "*" in endpoint.events:
                    try:
                        record = self.deliver(eid, event_type, payload)
                        results.append(record)
                    except ValueError:
                        pass
        return results

    def cleanup_expired(self) -> int:
        return self._idempotency.cleanup()

    def get_delivery_count(self, idempotency_key: str) -> int:
        record = self._idempotency.get(idempotency_key)
        return 1 if record else 0


__all__ = [
    "WebhookDeliveryService",
    "WebhookEndpoint",
    "DeliveryRecord",
    "DeliveryStatus",
    "EndpointStatus",
    "IdempotencyStore",
]
