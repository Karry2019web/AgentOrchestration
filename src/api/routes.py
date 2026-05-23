"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional
from fastapi.responses import StreamingResponse
import asyncio
import json

from src.agent import AgentRegistry, AgentStatus
from src.api.streaming import streaming_service, SSEError

router = APIRouter()
registry = AgentRegistry()

# In-memory workspace/role context — in production this would come from auth
_CURRENT_WORKSPACE = "workspace-default"
_CURRENT_ROLE = "admin"


def _get_auth_context() -> tuple:
    """Extract workspace and role from request context (stub for real auth)."""
    return _CURRENT_WORKSPACE, _CURRENT_ROLE


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


@router.post("/stream/cursors")
async def create_stream_cursor(agent_id: str, metadata: Optional[Dict] = None):
    """Create a new SSE streaming cursor scoped to the caller."""
    workspace_id, role = _get_auth_context()
    cursor_id = streaming_service.create_cursor(workspace_id, role, agent_id, metadata)
    return {"cursor_id": cursor_id, "workspace_id": workspace_id, "role": role}


@router.get("/stream/cursors")
async def list_stream_cursors():
    """List all cursors in the caller's workspace."""
    workspace_id, role = _get_auth_context()
    cursors = streaming_service.list_cursors(workspace_id, role)
    return {"cursors": cursors, "count": len(cursors)}


@router.get("/stream/cursors/{cursor_id}")
async def get_stream_cursor(cursor_id: str):
    """Get cursor details with ownership validation."""
    workspace_id, role = _get_auth_context()
    try:
        cursor = streaming_service.get_cursor(cursor_id, workspace_id, role)
        return cursor
    except SSEError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/stream/cursors/{cursor_id}/advance")
async def advance_stream_cursor(cursor_id: str, position: int):
    """Advance cursor position with ownership validation."""
    workspace_id, role = _get_auth_context()
    try:
        cursor = streaming_service.advance_cursor(cursor_id, workspace_id, role, position)
        return cursor
    except SSEError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/stream/cursors/{cursor_id}")
async def delete_stream_cursor(cursor_id: str):
    """Delete cursor with ownership validation."""
    workspace_id, role = _get_auth_context()
    try:
        streaming_service.delete_cursor(cursor_id, workspace_id, role)
        return {"status": "deleted"}
    except SSEError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/agents/{agent_id}/stream")
async def stream_agent_updates(agent_id: str):
    """SSE endpoint that streams agent updates, validated by cursor ownership."""
    workspace_id, role = _get_auth_context()

    cursor_id = streaming_service.create_cursor(workspace_id, role, agent_id)

    async def event_generator():
        try:
            for i in range(100):
                await asyncio.sleep(1)
                payload = {
                    "cursor_id": cursor_id,
                    "agent_id": agent_id,
                    "workspace_id": workspace_id,
                    "event": "heartbeat",
                    "sequence": i,
                }
                yield f"data: {json.dumps(payload)}\n\n"
        finally:
            streaming_service.delete_cursor(cursor_id, workspace_id, role)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Cursor-Id": cursor_id,
            "X-Workspace-Id": workspace_id,
        },
    )
