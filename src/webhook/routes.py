"""Webhook API routes."""

from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional
from pydantic import BaseModel

from .subscription import WebhookSubscriptionManager


class CreateSubscriptionRequest(BaseModel):
    url: str
    events: List[str]
    workspace_id: str = ""
    metadata: dict = {}


class UpdateEventsRequest(BaseModel):
    events: List[str]


manager = WebhookSubscriptionManager()
router = APIRouter(prefix="/webhooks")


@router.post("/subscriptions")
async def create_subscription(req: CreateSubscriptionRequest):
    """Create a webhook subscription with URL normalization and duplicate detection."""
    try:
        sub = manager.create_subscription(
            url=req.url,
            events=req.events,
            workspace_id=req.workspace_id,
            metadata=req.metadata,
        )
        return {
            "id": sub.id,
            "url": sub.url,
            "normalized_url": sub.normalized_url,
            "events": sub.events,
            "workspace_id": sub.workspace_id,
            "status": "created",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/subscriptions")
async def list_subscriptions(workspace_id: Optional[str] = Query(None)):
    """List webhook subscriptions, optionally filtered by workspace."""
    subs = manager.list_subscriptions(workspace_id or "")
    return {
        "subscriptions": [
            {
                "id": s.id,
                "url": s.url,
                "normalized_url": s.normalized_url,
                "events": s.events,
                "enabled": s.enabled,
                "workspace_id": s.workspace_id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "metadata": s.metadata,
            }
            for s in subs
        ],
        "count": len(subs),
    }


@router.get("/subscriptions/{subscription_id}")
async def get_subscription(subscription_id: str):
    """Get a webhook subscription by ID."""
    sub = manager.get_subscription(subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {
        "id": sub.id,
        "url": sub.url,
        "normalized_url": sub.normalized_url,
        "events": sub.events,
        "enabled": sub.enabled,
        "workspace_id": sub.workspace_id,
        "created_at": sub.created_at,
        "updated_at": sub.updated_at,
        "metadata": sub.metadata,
    }


@router.post("/subscriptions/{subscription_id}/disable")
async def disable_subscription(subscription_id: str):
    """Disable a webhook subscription."""
    if not manager.disable_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "disabled"}


@router.post("/subscriptions/{subscription_id}/enable")
async def enable_subscription(subscription_id: str):
    """Enable a disabled webhook subscription."""
    if not manager.enable_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "enabled"}


@router.put("/subscriptions/{subscription_id}/events")
async def update_subscription_events(subscription_id: str, req: UpdateEventsRequest):
    """Update the events for a subscription."""
    if not manager.update_events(subscription_id, req.events):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "updated", "events": req.events}


@router.delete("/subscriptions/{subscription_id}")
async def delete_subscription(subscription_id: str):
    """Delete a webhook subscription."""
    if not manager.delete_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"status": "deleted"}
