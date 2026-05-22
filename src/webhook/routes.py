"""Webhook API routes for endpoint registration and validation."""

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query

from src.webhook.validator import (
    WebhookEndpoint,
    WebhookConfig,
    validate_endpoint,
    is_localhost,
    configure_webhook,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks")

# In-memory store of registered webhook endpoints
_registered_endpoints: Dict[str, WebhookEndpoint] = {}
_webhook_config = WebhookConfig()


@router.post("/register")
async def register_webhook(url: str, name: Optional[str] = None):
    """Register a new webhook endpoint.

    Validates the endpoint URL before registration. Rejects localhost
    targets unless explicitly allowed via configuration.

    Args:
        url: The webhook endpoint URL.
        name: Optional friendly name for this webhook.

    Returns:
        Registration result with validation status.
    """
    endpoint = validate_endpoint(url, _webhook_config)

    if not endpoint.allowed:
        raise HTTPException(
            status_code=400,
            detail=endpoint.error or "Webhook endpoint validation failed",
        )

    hook_id = f"wh_{len(_registered_endpoints) + 1}"
    _registered_endpoints[hook_id] = endpoint

    logger.info(f"Registered webhook {hook_id}: {url}")
    return {
        "id": hook_id,
        "url": url,
        "name": name or f"webhook-{hook_id}",
        "status": "registered",
        "validated": True,
    }


@router.get("/list")
async def list_webhooks():
    """List all registered webhook endpoints."""
    return {
        "webhooks": [
            {"id": hid, "url": ep.url, "allowed": ep.allowed}
            for hid, ep in _registered_endpoints.items()
        ],
        "count": len(_registered_endpoints),
    }


@router.delete("/{hook_id}")
async def delete_webhook(hook_id: str):
    """Delete a registered webhook endpoint."""
    if hook_id not in _registered_endpoints:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del _registered_endpoints[hook_id]
    return {"status": "deleted", "id": hook_id}


@router.post("/validate")
async def validate_webhook_url(url: str = Query(..., description="Webhook URL to validate")):
    """Validate a webhook URL without registering it."""
    endpoint = validate_endpoint(url, _webhook_config)
    return {
        "url": url,
        "valid": endpoint.allowed,
        "error": endpoint.error,
        "is_localhost": is_localhost(url),
    }


@router.post("/config")
async def update_webhook_config(
    allow_localhost: bool = False,
    allowed_targets: Optional[List[str]] = None,
):
    """Update webhook configuration (e.g., allow localhost targets)."""
    global _webhook_config
    _webhook_config = WebhookConfig(
        allow_localhost=allow_localhost,
        allowed_localhost_targets=set(allowed_targets or []),
    )
    configure_webhook(allow_localhost, set(allowed_targets or []))
    return {
        "status": "configured",
        "allow_localhost": _webhook_config.allow_localhost,
        "allowed_localhost_targets": list(_webhook_config.allowed_localhost_targets),
    }
