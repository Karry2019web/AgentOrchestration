"""Webhook delivery module with idempotency key support."""

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


class IdempotencyKeyConflictError(Exception):
    """Raised when an idempotency key conflict is detected."""
    pass


class WebhookDeliveryError(Exception):
    """Raised when webhook delivery fails."""
    pass


class EndpointValidationError(Exception):
    """Raised when a webhook endpoint URL is invalid."""
    pass


@dataclass
class WebhookEvent:
    """An event to be delivered via webhook."""
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    idempotency_key: str = ""


@dataclass
class DeliveryRecord:
    """Record of a webhook delivery attempt."""
    event_id: str
    idempotency_key: str
    destination: str
    status: str
    status_code: int = 0
    response_body: str = ""
    timestamp: float = field(default_factory=time.time)
    attempt: int = 1


class IdempotencyStore:
    """In-memory store for idempotency keys with TTL.

    Stores idempotency keys mapped to their delivery results so that
    duplicate event delivery can be detected and handled safely.
    """

    def __init__(self, ttl_seconds: int = 3600):
        self._store: Dict[str, Tuple[str, float]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        if key not in self._store:
            return None
        status, stored_at = self._store[key]
        if time.time() - stored_at > self._ttl:
            del self._store[key]
            return None
        return {"status": status, "stored_at": stored_at}

    def set(self, key: str, status: str):
        self._store[key] = (status, time.time())

    def exists(self, key: str) -> bool:
        if key not in self._store:
            return False
        if time.time() - self._store[key][1] > self._ttl:
            del self._store[key]
            return False
        return True

    def cleanup(self) -> int:
        now = time.time()
        expired = [k for k in self._store if now - self._store[k][1] > self._ttl]
        for k in expired:
            del self._store[k]
        return len(expired)


class EndpointValidator:
    """Validates webhook endpoint URLs before delivery."""

    def __init__(self):
        self._allowed_schemes = {"https"}
        self._blocked_hosts: Set[str] = set()

    def validate(self, url: str) -> Tuple[bool, Optional[str]]:
        if not url or not url.strip():
            return False, "URL is empty"
        if not url.startswith("https://"):
            return False, "Only https scheme allowed"
        host = url.split("/")[2].lower() if "://" in url else url.lower()
        if host in self._blocked_hosts:
            return False, f"Host '{host}' is blocked"
        return True, None

    def block_host(self, host: str):
        self._blocked_hosts.add(host.lower().strip())


class WebhookDeliverer:
    """Handles idempotent webhook event delivery."""

    def __init__(
        self,
        idempotency_store: IdempotencyStore = None,
        endpoint_validator: EndpointValidator = None,
        max_retries: int = 3,
    ):
        self._idempotency = idempotency_store or IdempotencyStore()
        self._validator = endpoint_validator or EndpointValidator()
        self._max_retries = max_retries
        self._delivery_log: List[DeliveryRecord] = []

    @property
    def records(self) -> List[Dict[str, Any]]:
        return [asdict(r) for r in self._delivery_log]

    def _make_key(self, event: WebhookEvent, destination: str) -> str:
        raw = f"{event.event_id}:{destination}:{event.event_type}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _sig(self, payload: bytes, secret: str) -> str:
        return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

    async def deliver(
        self,
        event: WebhookEvent,
        destination: str,
        webhook_id: str,
        secret: str = None,
        idempotency_key: str = None,
    ) -> Dict[str, Any]:
        is_valid, err = self._validator.validate(destination)
        if not is_valid:
            self._delivery_log.append(DeliveryRecord(
                event_id=event.event_id, idempotency_key=idempotency_key or "",
                destination=destination, status="rejected",
            ))
            raise EndpointValidationError(err)

        key = idempotency_key or self._make_key(event, destination)
        existing = self._idempotency.get(key)
        if existing is not None:
            logger.info("Duplicate event detected (key=%s, event=%s)", key[:12], event.event_id)
            return {
                "status": "duplicate",
                "original_status": existing["status"],
                "event_id": event.event_id,
                "idempotency_key": key,
            }

        body = json.dumps({
            "event_id": event.event_id,
            "event_type": event.event_type,
            "payload": event.payload,
            "timestamp": event.timestamp,
        }, separators=(",", ":")).encode()

        headers = {
            "Content-Type": "application/json",
            "X-Webhook-ID": webhook_id,
            "X-Event-Type": event.event_type,
            "X-Idempotency-Key": key,
            "X-Delivery-Timestamp": str(int(time.time())),
        }
        if secret:
            sig = self._sig(body, secret)
            headers["X-Signature-256"] = sig
            event.idempotency_key = key

        last_error = None
        last_status = 0
        last_body = ""

        for attempt in range(1, self._max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(destination, content=body, headers=headers)
                last_status = resp.status_code
                last_body = resp.text[:500]
                if 200 <= last_status < 300:
                    self._idempotency.set(key, "delivered")
                    self._delivery_log.append(DeliveryRecord(
                        event_id=event.event_id, idempotency_key=key,
                        destination=destination, status="delivered",
                        status_code=last_status, response_body=last_body,
                        attempt=attempt,
                    ))
                    return {
                        "status": "delivered",
                        "status_code": last_status,
                        "event_id": event.event_id,
                        "idempotency_key": key,
                    }
                else:
                    last_error = f"HTTP {last_status}: {last_body[:200]}"
                    if attempt < self._max_retries:
                        await asyncio.sleep(self._backoff(attempt))
            except httpx.TimeoutException:
                last_error = "timeout"
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff(attempt))
            except httpx.RequestError as e:
                last_error = str(e)
                if attempt < self._max_retries:
                    await asyncio.sleep(self._backoff(attempt))

        self._idempotency.set(key, "failed")
        self._delivery_log.append(DeliveryRecord(
            event_id=event.event_id, idempotency_key=key,
            destination=destination, status="failed",
            status_code=last_status, response_body=last_error or "all retries exhausted",
            attempt=self._max_retries,
        ))
        raise WebhookDeliveryError(
            f"Delivery failed after {self._max_retries} attempts: {last_error}"
        )

    def _backoff(self, attempt: int) -> float:
        return min(1.0 * (2 ** (attempt - 1)), 30.0)

    def count(self) -> int:
        return len(self._delivery_log)

    def lookup(self, key: str) -> Optional[Dict[str, Any]]:
        for r in reversed(self._delivery_log):
            if r.idempotency_key == key:
                return asdict(r)
        cached = self._idempotency.get(key)
        if cached:
            return {"status": cached["status"], "cached": True}
        return None


_default_deliverer = None


def get_deliverer() -> WebhookDeliverer:
    global _default_deliverer
    if _default_deliverer is None:
        _default_deliverer = WebhookDeliverer()
    return _default_deliverer


def reset_deliverer():
    global _default_deliverer
    _default_deliverer = None


import asyncio
