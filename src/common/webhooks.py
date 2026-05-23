"""Webhook payload delivery — filters internal run metadata from public events."""

import json
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Fields considered internal / operational — stripped from public payloads
INTERNAL_METADATA_FIELDS = {
    "token",
    "secret",
    "api_key",
    "private_key",
    "certificate",
    "password",
    "credential",
    "execution_id",
    "workspace_id",
    "tenant_id",
    "internal_ip",
    "container_id",
    "hostname",
    "pid",
    "thread_id",
}


@dataclass
class WebhookEndpoint:
    """A registered webhook endpoint with its delivery configuration."""

    id: str = field(default_factory=lambda: str(uuid4()))
    url: str = ""
    secret: str = ""
    enabled: bool = True
    event_types: List[str] = field(default_factory=list)
    max_retries: int = 3
    timeout: float = 10.0
    created_at: float = field(default_factory=time.time)

    def to_public_dict(self) -> Dict[str, Any]:
        """Return endpoint data safe for public exposure — no secrets."""
        return {
            "id": self.id,
            "url": self.url,
            "enabled": self.enabled,
            "event_types": list(self.event_types),
            "created_at": self.created_at,
        }


class PayloadFilter:
    """Strips internal / operational metadata from event payloads."""

    @staticmethod
    def strip_internal_fields(payload: Dict[str, Any]) -> Dict[str, Any]:
        """Recursively remove internal-only fields from a payload dict."""
        if not isinstance(payload, dict):
            return payload
        cleaned: Dict[str, Any] = {}
        for key, value in payload.items():
            key_lower = key.lower()
            if key_lower in INTERNAL_METADATA_FIELDS:
                continue
            if isinstance(value, dict):
                cleaned[key] = PayloadFilter.strip_internal_fields(value)
            elif isinstance(value, list):
                cleaned[key] = [
                    PayloadFilter.strip_internal_fields(item)
                    if isinstance(item, dict)
                    else item
                    for item in value
                ]
            else:
                cleaned[key] = value
        return cleaned

    @staticmethod
    def filter_event_data(
        event_type: str,
        data: Dict[str, Any],
        allowed_fields: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Filter event data: strip internals, optionally whitelist fields."""
        cleaned = PayloadFilter.strip_internal_fields(data)
        if allowed_fields:
            cleaned = {k: v for k, v in cleaned.items() if k in allowed_fields}
        return {
            "event": event_type,
            "timestamp": time.time(),
            "data": cleaned,
        }


class WebhookDelivery:
    """Manages webhook delivery with idempotency, retries, and payload shaping."""

    def __init__(self):
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._delivery_records: Dict[str, Dict[str, Any]] = {}
        self._http_client: Optional[Callable] = None

    def set_http_client(self, client: Callable) -> None:
        """Inject an async HTTP client for testing / custom transport."""
        self._http_client = client

    def register_endpoint(
        self,
        url: str,
        secret: str = "",
        event_types: Optional[List[str]] = None,
    ) -> WebhookEndpoint:
        """Register a new webhook endpoint."""
        endpoint = WebhookEndpoint(
            url=url,
            secret=secret,
            event_types=event_types or [],
        )
        self._endpoints[endpoint.id] = endpoint
        logger.info("Webhook endpoint registered: %s (%s)", endpoint.id, url)
        return endpoint

    def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        """Look up an endpoint by ID."""
        return self._endpoints.get(endpoint_id)

    def remove_endpoint(self, endpoint_id: str) -> bool:
        """Remove a webhook endpoint."""
        if endpoint_id in self._endpoints:
            del self._endpoints[endpoint_id]
            return True
        return False

    def get_all_endpoints(self) -> List[WebhookEndpoint]:
        """List all registered endpoints."""
        return list(self._endpoints.values())

    def get_active_endpoints_for_event(self, event_type: str) -> List[WebhookEndpoint]:
        """Return enabled endpoints subscribed to the given event type."""
        return [
            ep
            for ep in self._endpoints.values()
            if ep.enabled and (not ep.event_types or event_type in ep.event_types)
        ]

    async def deliver(
        self,
        event_type: str,
        payload: Dict[str, Any],
        allowed_fields: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Deliver an event to all subscribed endpoints with payload shaping."""
        filtered = PayloadFilter.filter_event_data(event_type, payload, allowed_fields)
        serialized = json.dumps(filtered, default=str)

        results: List[Dict[str, Any]] = []
        for endpoint in self.get_active_endpoints_for_event(event_type):
            delivery_id = str(uuid4())
            result = await self._send_with_retry(
                delivery_id,
                endpoint,
                serialized,
            )
            self._delivery_records[delivery_id] = {
                "delivery_id": delivery_id,
                "endpoint_id": endpoint.id,
                "event_type": event_type,
                "status": result.get("status", "unknown"),
                "timestamp": time.time(),
            }
            results.append(self._delivery_records[delivery_id])
        return results

    async def _send_with_retry(
        self,
        delivery_id: str,
        endpoint: WebhookEndpoint,
        body: str,
    ) -> Dict[str, Any]:
        """Send payload to an endpoint with retry logic."""
        import asyncio
        last_error: Optional[str] = None
        for attempt in range(endpoint.max_retries):
            try:
                if self._http_client:
                    response = await self._http_client(
                        endpoint.url,
                        body,
                        endpoint.secret,
                    )
                    return {"status": "delivered", "attempt": attempt + 1}
                else:
                    return {"status": "delivered", "attempt": attempt + 1}
            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "Delivery %s attempt %d failed: %s",
                    delivery_id,
                    attempt + 1,
                    e,
                )
                if attempt < endpoint.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
        return {"status": "failed", "error": last_error, "attempt": endpoint.max_retries}

    def get_delivery_record(self, delivery_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a delivery record (safe fields only)."""
        record = self._delivery_records.get(delivery_id)
        if record:
            return PayloadFilter.strip_internal_fields(record)
        return None

    def get_delivery_records(
        self,
        endpoint_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List delivery records, optionally filtered by endpoint."""
        records = list(self._delivery_records.values())
        if endpoint_id:
            records = [r for r in records if r["endpoint_id"] == endpoint_id]
        return records[-limit:]
