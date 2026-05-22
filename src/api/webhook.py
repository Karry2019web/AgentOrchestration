"""Webhook delivery with idempotency key support."""

import hashlib
import hmac
import json
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IdempotencyStore:
    """In-memory TTL-based idempotency key store."""

    def __init__(self, ttl: int = 3600):
        self._store: Dict[str, Dict] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Dict]:
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.time() > entry.get("expires_at", 0):
            del self._store[key]
            return None
        return {"status": entry["status"], "stored_at": entry["stored_at"]}

    def set(self, key: str, status: str) -> None:
        self._store[key] = {
            "status": status,
            "stored_at": time.time(),
            "expires_at": time.time() + self._ttl,
        }

    def exists(self, key: str) -> bool:
        return self.get(key) is not None

    def cleanup(self) -> int:
        now = time.time()
        expired = [k for k, v in self._store.items() if now > v.get("expires_at", 0)]
        for k in expired:
            del self._store[k]
        return len(expired)


class EndpointValidator:
    """Validates webhook endpoint URLs."""

    def validate(self, url: str) -> Dict:
        if not url:
            return {"valid": False, "reason": "empty_url"}
        if not url.startswith("https://"):
            return {"valid": False, "reason": "non_https_url"}
        blocked_hosts = ["localhost", "127.0.0.1", "0.0.0.0", "[::1]"]
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname in blocked_hosts:
            return {"valid": False, "reason": "blocked_host"}
        return {"valid": True, "reason": "ok"}


class WebhookDeliverer:
    """Delivers webhook events with idempotency key deduplication."""

    def __init__(self, store: Optional[IdempotencyStore] = None,
                 validator: Optional[EndpointValidator] = None,
                 max_retries: int = 3,
                 secret: Optional[str] = None):
        self.store = store or IdempotencyStore()
        self.validator = validator or EndpointValidator()
        self.max_retries = max_retries
        self.secret = secret
        self._delivery_log: list = []

    def _make_idempotency_key(self, event_id: str, destination: str, event_type: str) -> str:
        raw = f"{event_id}|{destination}|{event_type}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def _sign_payload(self, payload: bytes) -> str:
        if not self.secret:
            return ""
        return hmac.new(self.secret.encode(), payload, hashlib.sha256).hexdigest()

    def deliver(self, event_id: str, destination: str, event_type: str,
                payload: Dict, tenant_id: str = "default") -> Dict:
        idem_key = self._make_idempotency_key(event_id, destination, event_type)

        # Check idempotency
        existing = self.store.get(idem_key)
        if existing:
            return {
                "status": "duplicate",
                "original_status": existing["status"],
                "idempotency_key": idem_key,
            }

        # Validate endpoint
        validation = self.validator.validate(destination)
        if not validation["valid"]:
            self.store.set(idem_key, "rejected")
            return {
                "status": "rejected",
                "reason": validation["reason"],
                "idempotency_key": idem_key,
            }

        # Simulate delivery with retries
        delivery_status = "delivered"
        for attempt in range(1, self.max_retries + 1):
            try:
                # In a real implementation, this would be an HTTP POST
                delivery_status = "delivered"
                break
            except Exception:
                if attempt < self.max_retries:
                    backoff = min(1.0 * 2 ** (attempt - 1), 30.0)
                    time.sleep(backoff)
                else:
                    delivery_status = "failed"

        self.store.set(idem_key, delivery_status)

        delivery_record = {
            "event_id": event_id,
            "destination": destination,
            "event_type": event_type,
            "tenant_id": tenant_id,
            "status": delivery_status,
            "idempotency_key": idem_key,
            "timestamp": time.time(),
        }
        self._delivery_log.append(delivery_record)

        result = {
            "status": delivery_status,
            "idempotency_key": idem_key,
        }
        if delivery_status == "delivered" and self.secret:
            payload_bytes = json.dumps(payload, separators=(",", ":")).encode()
            result["signature"] = self._sign_payload(payload_bytes)

        return result

    def get_delivery_log(self, limit: int = 50) -> list:
        return list(self._delivery_log[-limit:])

    def get_delivery(self, idempotency_key: str) -> Optional[Dict]:
        for record in reversed(self._delivery_log):
            if record.get("idempotency_key") == idempotency_key:
                return record
        return None

    def clear_log(self) -> int:
        count = len(self._delivery_log)
        self._delivery_log.clear()
        return count
