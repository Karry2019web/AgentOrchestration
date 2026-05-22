"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional, Set
from uuid import uuid4

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()

# In-memory webhook subscriptions store
_webhook_subscriptions: Dict[str, dict] = {}

# Allowlisted event types for webhook subscriptions
ALLOWED_EVENT_TYPES: Set[str] = {
    "agent.created",
    "agent.updated",
    "agent.deleted",
    "agent.started",
    "agent.stopped",
    "agent.failed",
    "run.completed",
    "run.failed",
    "workflow.started",
    "workflow.completed",
    "workflow.failed",
}


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


@router.post("/webhook/subscriptions")
async def create_webhook_subscription(url: str, event_types: List[str], description: Optional[str] = None):
    """Create a webhook subscription with event type allowlist validation."""
    invalid_types = [et for et in event_types if et not in ALLOWED_EVENT_TYPES]
    if invalid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid event type(s): {', '.join(invalid_types)}. "
                   f"Allowed types: {sorted(ALLOWED_EVENT_TYPES)}",
        )
    sub_id = str(uuid4())
    _webhook_subscriptions[sub_id] = {
        "id": sub_id,
        "url": url,
        "event_types": list(event_types),
        "description": description or "",
        "active": True,
        "created_at": __import__("datetime").datetime.utcnow().isoformat() + "Z",
    }
    return _webhook_subscriptions[sub_id]


@router.get("/webhook/subscriptions")
async def list_webhook_subscriptions():
    """List all webhook subscriptions."""
    return {"subscriptions": list(_webhook_subscriptions.values())}


@router.get("/webhook/subscriptions/{subscription_id}")
async def get_webhook_subscription(subscription_id: str):
    """Get a single webhook subscription by ID."""
    sub = _webhook_subscriptions.get(subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    return sub


@router.delete("/webhook/subscriptions/{subscription_id}")
async def delete_webhook_subscription(subscription_id: str):
    """Delete a webhook subscription."""
    if subscription_id not in _webhook_subscriptions:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    del _webhook_subscriptions[subscription_id]
    return {"status": "deleted"}


@router.patch("/webhook/subscriptions/{subscription_id}/toggle")
async def toggle_webhook_subscription(subscription_id: str):
    """Enable or disable a webhook subscription."""
    sub = _webhook_subscriptions.get(subscription_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    sub["active"] = not sub["active"]
    return {"subscription_id": subscription_id, "active": sub["active"]}
