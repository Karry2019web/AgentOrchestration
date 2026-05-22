"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, Header
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.api.models import RunDetailPublic, RunDetailAdmin, enforce_admin_fields, require_admin_role

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents", response_model=Dict[str, List[RunDetailPublic]])
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}", response_model=RunDetailAdmin)
async def get_agent(agent_id: str, x_role: Optional[str] = Header(None)):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_admin = require_admin_role(x_role)
    if not is_admin:
        return RunDetailPublic(**enforce_admin_fields(agent, is_admin=False))
    return RunDetailAdmin(**agent)


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


@router.get("/runs/{agent_id}", response_model=RunDetailPublic)
async def get_run_detail(agent_id: str, authorization: Optional[str] = Header(None)):
    """Get run detail with response model enforcing admin-only field visibility.

    Regular users see RunDetailPublic (no admin-only fields).
    Admin/owner users see RunDetailAdmin (full detail with infra fields).
    """
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    is_admin = False
    if authorization and authorization.startswith("Bearer "):
        token = authorization.replace("Bearer ", "").strip()
        if token.startswith("admin-") or token.startswith("owner-"):
            is_admin = True

    filtered = enforce_admin_fields(agent, is_admin=is_admin)
    return filtered
