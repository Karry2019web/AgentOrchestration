"""Webhook payload shaping — filter sensitive internal fields from public events."""

import re
import logging
from typing import Any, Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)

_INTERNAL_FIELDS: Set[str] = {
    "internal_api_key", "secret_token", "webhook_secret",
    "private_key", "access_token", "refresh_token",
    "session_id", "trace_id", "span_id",
    "worker_id", "replica_id", "k8s_namespace",
    "container_id", "pod_name", "node_name",
    "cluster_name", "region", "availability_zone",
    "instance_id", "vpc_id", "subnet_id",
    "_locked", "_version", "_etag", "_retry_count",
    "_processing_state", "_internal_status",
    "heartbeat_at", "last_ping", "internal_metrics",
}


class PayloadValidationError(Exception):
    """Raised when a payload fails validation rules."""


class PayloadShape(Enum):
    FULL = "full"
    MINIMAL = "minimal"
    REDACTED = "redacted"


@dataclass
class SensitiveFieldFilter:
    blocklist: Set[str] = field(default_factory=lambda: _INTERNAL_FIELDS.copy())
    allowlist: Set[str] = field(default_factory=set)
    pattern: Optional[str] = None
    _compiled: Optional[re.Pattern] = None

    def __post_init__(self):
        if self.pattern:
            self._compiled = re.compile(self.pattern)

    def filter(self, payload: Dict[str, Any], shape: PayloadShape = PayloadShape.FULL) -> Dict[str, Any]:
        return self._apply_shape(payload, shape)

    def _apply_shape(self, obj: Any, shape: PayloadShape, depth: int = 0) -> Any:
        if depth > 10:
            return obj
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if self._is_sensitive(key):
                    if shape == PayloadShape.REDACTED:
                        if isinstance(value, (str, bytes)):
                            result[key] = self._redact_value(str(value))
                        elif isinstance(value, (int, float)):
                            result[key] = 0
                        elif isinstance(value, bool):
                            result[key] = False
                        elif value is None:
                            result[key] = None
                        else:
                            result[key] = "[REDACTED]"
                    continue
                result[key] = self._apply_shape(value, shape, depth + 1)
            return result
        if isinstance(obj, list):
            return [self._apply_shape(item, shape, depth + 1) for item in obj]
        return obj

    def _is_sensitive(self, key: str) -> bool:
        if key in self.blocklist:
            return True
        if key.startswith("_"):
            return True
        if self._compiled and self._compiled.search(key):
            return True
        key_lower = key.lower()
        sensitive_patterns = ["secret", "token", "password", "credential", "key", "private", "internal"]
        if any(p in key_lower for p in sensitive_patterns) and key not in self.allowlist:
            return True
        return False

    def _redact_value(self, value: str) -> str:
        if len(value) <= 4:
            return "****"
        return value[:2] + "***" + value[-1]


class PayloadShapingMiddleware:
    def __init__(self, filter_obj: Optional[SensitiveFieldFilter] = None,
                 default_shape: PayloadShape = PayloadShape.FULL,
                 disabled_endpoints: Optional[List[str]] = None):
        self.filter = filter_obj or SensitiveFieldFilter()
        self.default_shape = default_shape
        self.disabled_endpoints = set(disabled_endpoints or [])

    def shape_payload(self, payload: Dict[str, Any],
                      shape: Optional[PayloadShape] = None,
                      endpoint_id: Optional[str] = None) -> Dict[str, Any]:
        if endpoint_id and endpoint_id in self.disabled_endpoints:
            raise PayloadValidationError(f"Endpoint {endpoint_id} is disabled or rotated — delivery rejected")
        shape = shape or self.default_shape
        return self.filter.filter(payload, shape)

    def register_disabled_endpoint(self, endpoint_id: str) -> None:
        self.disabled_endpoints.add(endpoint_id)

    def remove_disabled_endpoint(self, endpoint_id: str) -> None:
        self.disabled_endpoints.discard(endpoint_id)


class EndpointValidator:
    def __init__(self, shaping_middleware: PayloadShapingMiddleware):
        self.shaping = shaping_middleware

    def validate_and_register_endpoint(self, endpoint_id: str, url: str,
                                       is_rotated: bool = False) -> Dict[str, Any]:
        if not url.startswith(("https://", "http://")):
            raise PayloadValidationError(f"Invalid webhook URL scheme: {url}")
        if is_rotated:
            self.shaping.register_disabled_endpoint(endpoint_id)
        return {
            "endpoint_id": endpoint_id,
            "url": url,
            "status": "rotated" if is_rotated else "active",
            "deliveries_blocked": is_rotated,
        }

    def validate_delivery(self, endpoint_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        shaped = self.shaping.shape_payload(payload, endpoint_id=endpoint_id)
        return {"endpoint_id": endpoint_id, "delivered": True, "field_count": len(shaped)}
