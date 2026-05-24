"""Webhook delivery audit — monotonic status recording.

Prevents stale delivery status from overwriting newer results
by using sequence numbers for monotonic ordering.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional


INTERNAL_FIELDS = frozenset({
    "authorization", "debug", "headers", "internal_run_id",
    "private", "secret", "token", "trace_id",
})


class DeliveryRejected(ValueError):
    """Raised when a delivery cannot be recorded safely."""


@dataclass(frozen=True)
class WebhookEndpoint:
    workspace_id: str
    endpoint_id: str
    url: str
    enabled: bool = True


@dataclass
class DeliveryRecord:
    delivery_id: str
    status: str
    sequence: int
    timestamp: float
    payload: Dict[str, Any]


class DeliveryAuditStore:
    """Thread-safe webhook delivery audit store.

    Uses an incrementing sequence counter so that only deliveries
    with a higher sequence can overwrite existing records.
    """

    def __init__(self) -> None:
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._records: Dict[str, DeliveryRecord] = {}
        self._sequence: int = 0

    def register_endpoint(
        self, workspace_id: str, endpoint_id: str, url: str,
        enabled: bool = True,
    ) -> None:
        key = f"{workspace_id}:{endpoint_id}"
        self._endpoints[key] = WebhookEndpoint(
            workspace_id=workspace_id,
            endpoint_id=endpoint_id,
            url=url,
            enabled=enabled,
        )

    def _resolve(self, workspace_id: str, endpoint_id: str) -> WebhookEndpoint:
        key = f"{workspace_id}:{endpoint_id}"
        endpoint = self._endpoints.get(key)
        if endpoint is None:
            raise DeliveryRejected(f"endpoint {endpoint_id} not registered")
        if not endpoint.enabled:
            raise DeliveryRejected(f"endpoint {endpoint_id} is disabled")
        return endpoint

    def record_delivery(
        self,
        workspace_id: str,
        endpoint_id: str,
        delivery_id: str,
        status: str,
        payload: Dict[str, Any],
    ) -> DeliveryRecord:
        self._resolve(workspace_id, endpoint_id)
        if not isinstance(payload, dict):
            raise DeliveryRejected("payload must be a dict")
        self._sequence += 1
        seq = self._sequence
        timestamp = time.time()
        record_key = f"{workspace_id}:{endpoint_id}:{delivery_id}"
        existing = self._records.get(record_key)
        if existing is not None and seq <= existing.sequence:
            raise DeliveryRejected(
                f"stale delivery (seq {seq} <= existing {existing.sequence})"
            )
        sanitized = {
            k: v for k, v in payload.items()
            if k not in INTERNAL_FIELDS
        }
        record = DeliveryRecord(
            delivery_id=delivery_id,
            status=status,
            sequence=seq,
            timestamp=timestamp,
            payload=sanitized,
        )
        self._records[record_key] = record
        return record

    def get_last_delivery(
        self, workspace_id: str, endpoint_id: str, delivery_id: str,
    ) -> Optional[DeliveryRecord]:
        return self._records.get(f"{workspace_id}:{endpoint_id}:{delivery_id}")

    def remove_endpoint(self, workspace_id: str, endpoint_id: str) -> None:
        key = f"{workspace_id}:{endpoint_id}"
        self._endpoints.pop(key, None)
