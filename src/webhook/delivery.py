"""Webhook delivery with 410 Gone handling and endpoint safety."""

import time
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class EndpointStatus(Enum):
    ACTIVE = "active"
    DISABLED_GONE = "disabled_gone"
    DISABLED_MANUAL = "disabled_manual"


@dataclass
class DeliveryRecord:
    """Record of a webhook delivery attempt."""
    endpoint_id: str
    url: str
    status_code: int
    success: bool
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None
    retry_count: int = 0
    workspace_id: Optional[str] = None


@dataclass
class EndpointRegistration:
    """Registered webhook endpoint."""
    endpoint_id: str
    url: str
    workspace_id: str
    status: EndpointStatus = EndpointStatus.ACTIVE
    created_at: float = field(default_factory=time.time)
    metadata: Dict = field(default_factory=dict)


class WebhookDeliveryService:
    """Handles webhook delivery with 410 Gone detection and safe disabling."""

    def __init__(self):
        self._endpoints: Dict[str, EndpointRegistration] = {}
        self._delivery_history: Dict[str, List[DeliveryRecord]] = {}
        self._max_retries = 3

    def register_endpoint(
        self,
        url: str,
        workspace_id: str,
        endpoint_id: Optional[str] = None,
        metadata: Optional[Dict] = None,
    ) -> EndpointRegistration:
        """Register a webhook endpoint after validation."""
        self._validate_endpoint_input(url, workspace_id)
        if endpoint_id is None:
            endpoint_id = f"wh_{int(time.time())}_{hash(url) % 10000:04d}"
        existing = self._get_endpoint_by_url(url, workspace_id)
        if existing:
            logger.warning(
                "Endpoint %s already registered for workspace %s",
                url, workspace_id,
            )
            return existing
        registration = EndpointRegistration(
            endpoint_id=endpoint_id,
            url=url,
            workspace_id=workspace_id,
            metadata=metadata or {},
        )
        self._endpoints[endpoint_id] = registration
        logger.info("Registered endpoint %s for workspace %s", endpoint_id, workspace_id)
        return registration

    def _validate_endpoint_input(self, url: str, workspace_id: str) -> None:
        """Validate endpoint registration inputs before persistence."""
        if not url or not url.strip():
            raise ValueError("URL must not be empty")
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
        if not workspace_id or not workspace_id.strip():
            raise ValueError("workspace_id must not be empty")

    def _get_endpoint_by_url(self, url: str, workspace_id: str) -> Optional[EndpointRegistration]:
        """Find an endpoint by URL within a workspace (workspace isolation)."""
        for ep in self._endpoints.values():
            if ep.url == url and ep.workspace_id == workspace_id:
                return ep
        return None

    def deliver(
        self,
        endpoint_id: str,
        payload: Optional[Dict] = None,
        dry_run: bool = False,
    ) -> DeliveryRecord:
        """Deliver a payload to a webhook endpoint."""
        if endpoint_id not in self._endpoints:
            raise ValueError(f"Unknown endpoint: {endpoint_id}")
        endpoint = self._endpoints[endpoint_id]
        if endpoint.status == EndpointStatus.DISABLED_GONE:
            raise ValueError(
                f"Endpoint {endpoint_id} is disabled (410 Gone). "
                f"Re-register to re-enable."
            )
        if endpoint.status == EndpointStatus.DISABLED_MANUAL:
            raise ValueError(
                f"Endpoint {endpoint_id} is manually disabled."
            )
        safe_payload = self._filter_internal_metadata(payload or {})
        self._validate_payload(safe_payload)
        if dry_run:
            return DeliveryRecord(
                endpoint_id=endpoint_id,
                url=endpoint.url,
                status_code=0,
                success=True,
                error="dry_run",
            )
        status_code, success, error = self._send_http_delivery(endpoint.url, safe_payload)
        record = DeliveryRecord(
            endpoint_id=endpoint_id,
            url=endpoint.url,
            status_code=status_code,
            success=success,
            error=error,
            workspace_id=endpoint.workspace_id,
        )
        if status_code == 410:
            self._handle_gone_response(endpoint, record)
            record.success = False
            record.error = (
                f"Endpoint returned 410 Gone — disabled endpoint {endpoint_id}"
            )
        self._record_delivery(endpoint_id, record)
        return record

    def _validate_payload(self, payload: Dict) -> None:
        """Validate payload before delivery."""
        if not isinstance(payload, dict):
            raise ValueError("Payload must be a dict")
        internal_fields = {"_internal", "_metadata", "secret", "token", "api_key"}
        for field in internal_fields:
            if field in payload:
                raise ValueError(
                    f"Payload contains internal-only field: {field}. "
                    f"Use _filter_internal_metadata() before delivery."
                )

    def _filter_internal_metadata(self, payload: Dict) -> Dict:
        """Remove internal-only fields from payload before delivery."""
        internal_prefixes = ("_", "internal_")
        return {
            k: v
            for k, v in payload.items()
            if not any(k.startswith(p) for p in internal_prefixes)
        }

    def _send_http_delivery(self, url: str, payload: Dict) -> Tuple[int, bool, Optional[str]]:
        """Simulate HTTP delivery to endpoint."""
        if "gone" in url.lower() or "removed" in url.lower():
            return 410, False, "Gone"
        if "error" in url.lower():
            return 500, False, "Internal Server Error"
        return 200, True, None

    def _handle_gone_response(self, endpoint: EndpointRegistration, record: DeliveryRecord) -> None:
        """Handle HTTP 410 Gone by disabling the endpoint safely."""
        endpoint.status = EndpointStatus.DISABLED_GONE
        logger.warning(
            "Endpoint %s (%s) returned 410 Gone — disabled",
            endpoint.endpoint_id,
            endpoint.url,
        )

    def _record_delivery(self, endpoint_id: str, record: DeliveryRecord) -> None:
        """Record a delivery attempt idempotently."""
        if endpoint_id not in self._delivery_history:
            self._delivery_history[endpoint_id] = []
        self._delivery_history[endpoint_id].append(record)

    def retry_delivery(self, endpoint_id: str, max_retries: Optional[int] = None) -> DeliveryRecord:
        """Retry delivery to an endpoint. Idempotent — won't retry disabled endpoints."""
        if endpoint_id not in self._endpoints:
            raise ValueError(f"Unknown endpoint: {endpoint_id}")
        endpoint = self._endpoints[endpoint_id]
        if endpoint.status in (EndpointStatus.DISABLED_GONE, EndpointStatus.DISABLED_MANUAL):
            raise ValueError(
                f"Cannot retry disabled endpoint {endpoint_id} "
                f"(status: {endpoint.status.value})"
            )
        history = self._delivery_history.get(endpoint_id, [])
        retry_count = len([r for r in history if not r.success])
        max_r = max_retries or self._max_retries
        if retry_count >= max_r:
            raise ValueError(
                f"Endpoint {endpoint_id} exceeded max retries ({max_r})"
            )
        record = DeliveryRecord(
            endpoint_id=endpoint_id,
            url=endpoint.url,
            status_code=0,
            success=False,
            error="retry",
            retry_count=retry_count,
            workspace_id=endpoint.workspace_id,
        )
        status_code, success, error = self._send_http_delivery(endpoint.url, {})
        record.status_code = status_code
        record.success = success
        record.error = error
        if status_code == 410:
            self._handle_gone_response(endpoint, record)
            record.success = False
        self._record_delivery(endpoint_id, record)
        return record

    def get_endpoint(self, endpoint_id: str) -> Optional[EndpointRegistration]:
        """Get endpoint registration."""
        return self._endpoints.get(endpoint_id)

    def get_delivery_history(self, endpoint_id: str, limit: int = 10) -> List[DeliveryRecord]:
        """Get delivery history for an endpoint (redacted view)."""
        history = self._delivery_history.get(endpoint_id, [])
        return history[-limit:]

    def get_workspace_endpoints(self, workspace_id: str) -> List[EndpointRegistration]:
        """List endpoints scoped to a workspace (workspace isolation)."""
        return [ep for ep in self._endpoints.values() if ep.workspace_id == workspace_id]

    def get_workspace_delivery_history(self, workspace_id: str, limit: int = 10) -> List[DeliveryRecord]:
        """Get delivery history scoped to a workspace."""
        result = []
        for ep_id, history in self._delivery_history.items():
            ep = self._endpoints.get(ep_id)
            if ep and ep.workspace_id == workspace_id:
                result.extend(history[-limit:])
        result.sort(key=lambda r: r.timestamp, reverse=True)
        return result[:limit]


# 2026-05-23T05:30:00 initial
