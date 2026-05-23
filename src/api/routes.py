"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, Request
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from .auth import (
    User, require_permission, Permission, UserRole, require_role,
)

router = APIRouter()
registry = AgentRegistry()


# --- Template store (in-memory for development) ---

_templates: Dict[str, dict] = {
    "template-default": {
        "id": "template-default",
        "name": "default-agent",
        "type": "worker.processor",
        "config": {"timeout": 300, "retries": 3},
        "version": "1.0.0",
        "owner": "system",
        "created_at": 1700000000.0,
    },
    "template-gpu": {
        "id": "template-gpu",
        "name": "gpu-worker",
        "type": "worker.gpu",
        "config": {"timeout": 600, "retries": 2, "gpu": True},
        "version": "2.1.0",
        "owner": "system",
        "created_at": 1700000000.0,
    },
}


def _clone_template(template_id: str, new_name: str, user: User) -> dict:
    """Clone a template into a new agent. Internal helper with RBAC."""
    if template_id not in _templates:
        raise HTTPException(status_code=404, detail=f"Template {template_id} not found")

    src = _templates[template_id]

    # Owner-based access control: non-admin users can only clone templates they own
    if user.role not in (UserRole.ADMIN, UserRole.OPERATOR):
        if src["owner"] != user.username and src["owner"] != "system":
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: template {template_id} is owned by {src['owner']}",
            )

    # Clone by registering a new agent from the template's configuration
    agent_id = registry.register(new_name, src["type"], src.get("config", {}).copy())

    return {
        "agent_id": agent_id,
        "name": new_name,
        "source_template": template_id,
        "status": "cloned",
        "type": src["type"],
        "version": src["version"],
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


# --- Template endpoints with role-based access control ---

@router.get("/templates")
async def list_templates():
    """List all available agent templates. Read access for all authenticated users."""
    return {"templates": list(_templates.values())}


@router.get("/templates/{template_id}")
async def get_template(template_id: str):
    """Get details of a specific template."""
    if template_id not in _templates:
        raise HTTPException(status_code=404, detail="Template not found")
    return _templates[template_id]


@router.post(
    "/templates/{template_id}/clone",
    summary="Clone an agent template into a new agent",
    description=(
        "Clone an existing template to create a new agent instance. "
        "Requires the templates:clone permission (Developer role or higher). "
        "Operators and Admins can clone any template; Developers can clone "
        "system templates and their own templates."
    ),
)
async def clone_template(
    template_id: str,
    name: str,
    user: User = Depends(require_permission(Permission.CLONE_TEMPLATES)),
):
    """Clone an agent template into a new agent. Requires templates:clone permission."""
    result = _clone_template(template_id, name, user)
    return result
