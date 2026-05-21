"""API route definitions."""

import os
import uuid
import time
from fastapi import APIRouter, HTTPException, Depends, File, UploadFile, Form
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus

router = APIRouter()
registry = AgentRegistry()

MAX_ARTIFACT_SIZE = int(os.getenv("AO_MAX_ARTIFACT_SIZE", str(50 * 1024 * 1024)))


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
    if not file.filename or file.filename.strip() == "":
        raise HTTPException(status_code=400, detail="Filename is required")

    content = await file.read()
    size = len(content)

    if size > MAX_ARTIFACT_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"Artifact size {size} exceeds maximum allowed {MAX_ARTIFACT_SIZE} bytes"
        )

    artifact_id = str(uuid.uuid4())
    return {
        "artifact_id": artifact_id,
        "filename": file.filename,
        "size": size,
        "status": "uploaded"
    }
