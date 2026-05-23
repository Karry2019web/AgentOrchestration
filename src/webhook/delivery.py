"""Webhook delivery with idempotency, retry, and workspace isolation."""

import time
import json
import hashlib
import logging
import asyncio
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

from .shaping import PayloadShapingMiddleware, PayloadShape, PayloadValidationError

logger = logging.getLogger(__name__)


class DeliveryStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    REJECTED = "rejected"
    RETRYING = "retrying"


@dataclass
class DeliveryRecord:
    delivery_id: str
    endpoint_id: str
    workspace_id: str
    status: DeliveryStatus
    attempt: int = 1
    max_attempts: int = 3
    status_code: Optional[int] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)


class WebhookDeliveryManager:
    def __init__(self, shaping: PayloadShapingMiddleware,
                 max_retries: int = 3, retry_backoff: float = 1.0):
        self.shaping = shaping
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self._records: Dict[str, DeliveryRecord] = {}
        self._idempotency_cache: Set[str] = set()

    def _compute_payload_hash(self, payload: Dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _make_delivery_id(self, endpoint_id: str, payload_hash: str) -> str:
        raw = f"{endpoint_id}:{payload_hash}:{int(time.time() // 60)}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def check_idempotent(self, endpoint_id: str, payload: Dict[str, Any]) -> bool:
        payload_hash = self._compute_payload_hash(payload)
        delivery_id = self._make_delivery_id(endpoint_id, payload_hash)
        return delivery_id in self._idempotency_cache

    async def deliver(self, endpoint_id: str, workspace_id: str,
                      url: str, payload: Dict[str, Any],
                      shape: Optional[PayloadShape] = None) -> DeliveryRecord:
        payload_hash = self._compute_payload_hash(payload)
        delivery_id = self._make_delivery_id(endpoint_id, payload_hash)
        if delivery_id in self._idempotency_cache:
            return self._records[delivery_id]
        shaped = self.shaping.shape_payload(payload, shape, endpoint_id=endpoint_id)
        record = DeliveryRecord(
            delivery_id=delivery_id, endpoint_id=endpoint_id,
            workspace_id=workspace_id, status=DeliveryStatus.RETRYING,
        )
        self._records[delivery_id] = record
        for attempt in range(1, self.max_retries + 1):
            record.attempt = attempt
            try:
                import httpx
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        url, json=shaped,
                        headers={"Content-Type": "application/json",
                                 "X-Delivery-Id": delivery_id,
                                 "X-Workspace-Id": workspace_id},
                    )
                record.status_code = response.status_code
                if 200 <= response.status_code < 300:
                    record.status = DeliveryStatus.SUCCESS
                    self._idempotency_cache.add(delivery_id)
                    return record
                if response.status_code == 410:
                    self.shaping.register_disabled_endpoint(endpoint_id)
                    record.status = DeliveryStatus.REJECTED
                    record.error = "Endpoint returned 410 Gone"
                    return record
                record.error = f"HTTP {response.status_code}"
            except Exception as e:
                record.error = str(e)
            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_backoff * (2 ** (attempt - 1)))
        record.status = DeliveryStatus.FAILED
        return record

    def get_delivery(self, delivery_id: str) -> Optional[DeliveryRecord]:
        return self._records.get(delivery_id)

    def get_workspace_deliveries(self, workspace_id: str) -> List[DeliveryRecord]:
        return [r for r in self._records.values() if r.workspace_id == workspace_id]
