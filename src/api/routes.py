"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, Header, Request
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.webhook import WebhookVerifier, WebhookSignatureError, ReplayAttackError, verify_webhook

router = APIRouter()
registry = AgentRegistry()

# In-memory webhook subscription store
_webhook_subscriptions: Dict[str, dict] = {}


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}


# ---------------------------------------------------------------------------
# Webhook subscription endpoints
# ---------------------------------------------------------------------------


@router.post("/webhooks/subscriptions")
async def create_webhook_subscription(
    url: str,
    events: List[str],
    secret: str,
    description: Optional[str] = None,
):
    """Register a new webhook subscription.

    The *secret* is used later to sign outbound payloads so that the
    subscriber can verify authenticity.  Subscribers should also sign
    their inbound callbacks with the same secret.
    """
    sub_id = f"wh_{len(_webhook_subscriptions) + 1:04d}"
    _webhook_subscriptions[sub_id] = {
        "id": sub_id,
        "url": url,
        "events": events,
        "description": description or "",
        "active": True,
        "created_at": "2026-05-23T00:00:00Z",
    }
    return {"subscription_id": sub_id, "status": "created"}


@router.get("/webhooks/subscriptions")
async def list_webhook_subscriptions():
    """List all registered webhook subscriptions."""
    return {"subscriptions": list(_webhook_subscriptions.values())}


@router.delete("/webhooks/subscriptions/{subscription_id}")
async def delete_webhook_subscription(subscription_id: str):
    """Remove a webhook subscription."""
    if subscription_id not in _webhook_subscriptions:
        raise HTTPException(status_code=404, detail="Subscription not found")
    del _webhook_subscriptions[subscription_id]
    return {"status": "deleted"}


@router.post("/webhooks/callback")
async def webhook_callback(
    request: Request,
    x_webhook_signature: Optional[str] = Header(None, alias="X-Webhook-Signature"),
):
    """Receive an inbound webhook callback with replay-window protection.

    The ``X-Webhook-Signature`` header is verified before the payload is
    processed.  Signatures outside the 5-minute replay window are rejected
    as potential replay attacks.
    """
    if not x_webhook_signature:
        raise HTTPException(status_code=401, detail="Missing X-Webhook-Signature header")
    try:
        body = await request.json()
        result = verify_webhook(body, x_webhook_signature)
        return {
            "status": "accepted",
            "timestamp": result["timestamp"],
            "age_seconds": result["age_seconds"],
        }
    except ReplayAttackError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except WebhookSignatureError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {e}")
