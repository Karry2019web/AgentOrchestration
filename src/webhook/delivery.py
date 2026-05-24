"""Webhook delivery service — Manages deliveries, idempotency, and retry logic."""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class DeliveryRecord:
    """Record of a webhook delivery attempt."""
    delivery_id: str
    event_id: str
    subscription_id: str
    endpoint_url: str
    status: str
    attempt: int = 1
    max_attempts: int = 3
    response_status: Optional[int] = None
    error_message: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WebhookDeliveryService:
    """Manages webhook delivery with idempotency, retry, and workspace isolation."""

    def __init__(self, max_attempts: int = 3, retry_delays_seconds: List[int] = None):
        self._max_attempts = max_attempts
        self._retry_delays = retry_delays_seconds or [5, 30, 120]
        self._deliveries: Dict[str, DeliveryRecord] = {}
        self._subscriptions: Dict[str, Dict[str, Any]] = {}
        self._delivered_event_ids: Set[str] = set()

    def register_subscription(self, subscription_id: str, config: Dict[str, Any]) -> None:
        self._subscriptions[subscription_id] = {
            "id": subscription_id,
            "endpoint_url": config.get("endpoint_url"),
            "workspace_id": config.get("workspace_id", "default"),
            "event_types": config.get("event_types", []),
            "enabled": config.get("enabled", True),
            "created_at": config.get("created_at", datetime.now(timezone.utc).isoformat()),
        }

    def get_subscription(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        return self._subscriptions.get(subscription_id)

    def _generate_idempotency_key(self, event_id: str, subscription_id: str) -> str:
        raw = f"{event_id}:{subscription_id}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def is_event_already_delivered(self, event_id: str, subscription_id: str) -> bool:
        key = self._generate_idempotency_key(event_id, subscription_id)
        return key in self._delivered_event_ids

    def deliver_event(self, event_id: str, subscription_id: str, payload: Dict[str, Any], use_http: bool = False) -> DeliveryRecord:
        sub = self._subscriptions.get(subscription_id)
        if not sub:
            record = DeliveryRecord(delivery_id=str(uuid4()), event_id=event_id, subscription_id=subscription_id, endpoint_url="unknown", status="failed", error_message="Subscription not found")
            self._deliveries[record.delivery_id] = record
            return record

        if not sub.get("enabled", True):
            record = DeliveryRecord(delivery_id=str(uuid4()), event_id=event_id, subscription_id=subscription_id, endpoint_url=sub["endpoint_url"], status="failed", error_message="Subscription is disabled")
            self._deliveries[record.delivery_id] = record
            return record

        idem_key = self._generate_idempotency_key(event_id, subscription_id)
        if idem_key in self._delivered_event_ids:
            return DeliveryRecord(delivery_id=str(uuid4()), event_id=event_id, subscription_id=subscription_id, endpoint_url=sub["endpoint_url"], status="delivered", response_status=200, error_message="Idempotent delivery")

        record = self._attempt_delivery(sub, payload, event_id, use_http)
        if record.status == "delivered":
            self._delivered_event_ids.add(idem_key)
        else:
            record = self._retry_delivery(sub, payload, record, use_http)

        self._deliveries[record.delivery_id] = record
        return record

    def _attempt_delivery(self, subscription, payload, event_id, use_http, attempt=1):
        delivery_id = str(uuid4())
        record = DeliveryRecord(delivery_id=delivery_id, event_id=event_id, subscription_id=subscription["id"], endpoint_url=subscription["endpoint_url"], status="pending", attempt=attempt, max_attempts=self._max_attempts)

        if not use_http:
            record.status = "delivered"
            record.response_status = 200
            return record

        try:
            import httpx
            resp = httpx.post(subscription["endpoint_url"], json=payload, headers={"Content-Type": "application/json", "X-Webhook-ID": event_id, "X-Delivery-ID": delivery_id, "User-Agent": "AgentOrchestrator-Webhook/2.4.1"}, timeout=10.0)
            record.response_status = resp.status_code
            if 200 <= resp.status_code < 300:
                record.status = "delivered"
            else:
                record.status = "failed"
                record.error_message = f"HTTP {resp.status_code}"
        except Exception as e:
            record.status = "failed"
            record.error_message = str(e)

        return record

    def _retry_delivery(self, subscription, payload, failed_record, use_http):
        current = failed_record
        for attempt in range(failed_record.attempt + 1, self._max_attempts + 1):
            delay = self._retry_delays[min(attempt - 2, len(self._retry_delays) - 1)]
            time.sleep(delay)
            current = self._attempt_delivery(subscription, payload, failed_record.event_id, use_http, attempt)
            self._deliveries[current.delivery_id] = current
            if current.status == "delivered":
                return current
        return current

    def get_delivery(self, delivery_id: str) -> Optional[DeliveryRecord]:
        return self._deliveries.get(delivery_id)

    def get_deliveries_for_event(self, event_id: str) -> List[DeliveryRecord]:
        return [r for r in self._deliveries.values() if r.event_id == event_id]

    def get_deliveries_for_subscription(self, subscription_id: str) -> List[DeliveryRecord]:
        return [r for r in self._deliveries.values() if r.subscription_id == subscription_id]

    def workspace_deliveries(self, workspace_id: str) -> List[DeliveryRecord]:
        sub_ids = {sid for sid, sub in self._subscriptions.items() if sub.get("workspace_id") == workspace_id}
        return [r for r in self._deliveries.values() if r.subscription_id in sub_ids]
