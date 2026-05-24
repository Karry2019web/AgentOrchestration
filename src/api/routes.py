"""API route definitions."""

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Header, Request

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()


class IdempotencyRegistry:
    """Cross-user idempotency key registry for task creation.

    Ensures that a given idempotency key can only be used once across
    all users, preventing duplicate task creation from retries or
    forwarded requests that cross authentication boundaries.
    """

    def __init__(self, ttl: float = 86400.0):
        self._store: Dict[str, str] = {}
        self._ttl = ttl

    def check_and_register(self, idempotency_key: str, user: str) -> bool:
        """Return True if the key is new and was registered. False if already claimed by another user."""
        existing = self._store.get(idempotency_key)
        if existing is not None and existing != user:
            return False
        if existing == user:
            return True
        self._store[idempotency_key] = user
        return True

    def has_key(self, idempotency_key: str) -> bool:
        return idempotency_key in self._store

    def get_owner(self, idempotency_key: str) -> Optional[str]:
        return self._store.get(idempotency_key)


idempotency_registry = IdempotencyRegistry()
_idempotency_results: Dict[str, Dict[str, Any]] = {}


def _resolve_user(request: Request) -> str:
    """Extract a stable user identifier from the request."""
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()[:16] if token else "anonymous"


@router.post("/tasks")
async def create_task(request: Request, task: Dict[str, Any]):
    """Create a new task with cross-user idempotency key enforcement."""
    idempotency_key = task.get("idempotency_key")
    if not idempotency_key:
        raise HTTPException(status_code=400, detail="idempotency_key is required")

    user = _resolve_user(request)

    if not idempotency_registry.check_and_register(idempotency_key, user):
        raise HTTPException(
            status_code=409,
            detail=f"Idempotency key '{idempotency_key}' has already been used by a different user",
        )

    if idempotency_key in _idempotency_results:
        return _idempotency_results[idempotency_key]

    from src.orchestrator.scheduler import TaskScheduler
    scheduler = TaskScheduler()

    agent_id = task.get("agent_id")
    if not agent_id:
        raise HTTPException(status_code=400, detail="agent_id is required")

    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    task_payload = task.get("payload", {})
    task_priority = task.get("priority", 0)

    task_id = scheduler.enqueue({
        "type": task.get("type", "default"),
        "payload": task_payload,
        "target_agent": agent_id,
    }, priority=task_priority)

    result = {
        "task_id": task_id,
        "status": "created",
        "agent_id": agent_id,
    }

    _idempotency_results[idempotency_key] = result
    return result


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
