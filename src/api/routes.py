"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional
from pydantic import BaseModel

from src.agent.registry import AgentRegistry, AgentStatus
from src.api.streaming import StreamingService

router = APIRouter()
registry = AgentRegistry()
streaming = StreamingService(registry)


# --- Original Agent Management Routes ---


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


# --- SSE Streaming Routes ---


class CursorCreateRequest(BaseModel):
    workspace_id: str
    role: str
    agent_id: str


class CursorValidateRequest(BaseModel):
    cursor_id: str
    workspace_id: str
    role: str
    agent_id: Optional[str] = None


@router.post("/stream/cursors", status_code=201)
async def create_stream_cursor(body: CursorCreateRequest):
    """Create a new SSE cursor tied to a specific workspace and role."""
    cursor = streaming.create_cursor(
        workspace_id=body.workspace_id,
        role=body.role,
        agent_id=body.agent_id,
    )
    return {
        "cursor_id": cursor.cursor_id,
        "workspace_id": cursor.workspace_id,
        "role": cursor.role,
        "agent_id": cursor.agent_id,
    }


@router.post("/stream/cursors/validate")
async def validate_stream_cursor(body: CursorValidateRequest):
    """Validate SSE cursor ownership — scoped to workspace and role.

    Returns a deterministic 4xx response without performing the protected
    lookup or mutation when validation fails.
    """
    try:
        cursor = streaming.validate_cursor_ownership(
            cursor_id=body.cursor_id,
            workspace_id=body.workspace_id,
            role=body.role,
            agent_id=body.agent_id,
        )
        return {
            "valid": True,
            "cursor_id": cursor.cursor_id,
            "workspace_id": cursor.workspace_id,
            "role": cursor.role,
            "agent_id": cursor.agent_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/stream/events/{cursor_id}")
async def stream_events(cursor_id: str, workspace_id: str, role: str):
    """Stream events for an agent given a validated cursor.

    Validates cursor ownership before any event data lookup or mutation.
    """
    try:
        cursor = streaming.validate_cursor_ownership(
            cursor_id=cursor_id,
            workspace_id=workspace_id,
            role=role,
        )
        return {
            "status": "streaming",
            "cursor_id": cursor.cursor_id,
            "workspace_id": cursor.workspace_id,
            "events": [],
        }
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.delete("/stream/cursors/{cursor_id}")
async def delete_stream_cursor(cursor_id: str, workspace_id: str, role: str):
    """Delete an SSE cursor after ownership validation."""
    try:
        streaming.validate_cursor_ownership(
            cursor_id=cursor_id,
            workspace_id=workspace_id,
            role=role,
        )
        streaming.delete_cursor(cursor_id)
        return {"status": "deleted", "cursor_id": cursor_id}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
