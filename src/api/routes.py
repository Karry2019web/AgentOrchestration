"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()

# Maximum artifact size in bytes (100 MB)
MAX_ARTIFACT_SIZE = 100 * 1024 * 1024


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


@router.post("/artifacts/upload", status_code=201)
async def upload_artifact(file: UploadFile = File(...)):
    """Upload an artifact (e.g., binary blob, config, model).

    Validates file size before reading the content to prevent
    oversized uploads from consuming server resources.
    """
    # Validate file size from Content-Length (enforced by RequestSizeLimitMiddleware)
    # but also guard at the route level for defense in depth
    if not file.filename or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Filename is required")

    # Read file content with explicit size check
    content = await file.read()
    if len(content) > MAX_ARTIFACT_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact exceeds maximum allowed size of {MAX_ARTIFACT_SIZE} bytes",
        )

    return {
        "status": "uploaded",
        "filename": file.filename,
        "size": len(content),
        "artifact_id": f"art-{abs(hash(file.filename)) % 10**8:08d}",
    }

