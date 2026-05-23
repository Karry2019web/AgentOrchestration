"""API route definitions."""

import uuid as _uuid
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Query

from src.agent import AgentRegistry, AgentStatus
from src.common.logging import audit, AuditTrail

router = APIRouter()
registry = AgentRegistry()


# In-memory export store simulation
_exports: Dict[str, Dict] = {}


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


# --- Export / Download endpoints with audit trail ---


@router.post("/exports")
async def create_export(
    export_type: str = Query(..., description="Type of export (e.g. csv, json)"),
    actor: str = Query("system", description="Requesting actor"),
):
    """Create an export job and return a download link."""
    export_id = str(_uuid.uuid4())
    _exports[export_id] = {
        "id": export_id,
        "type": export_type,
        "status": "completed",
        "created_by": actor,
        "download_url": f"/api/v2/exports/{export_id}/download",
    }
    audit.record(
        action="export.create",
        actor=actor,
        target_id=export_id,
        target_type="export",
        result="success",
        metadata={"export_type": export_type},
    )
    return _exports[export_id]


@router.get("/exports/{export_id}/download")
async def download_export(
    export_id: str,
    actor: str = Query("system", description="Requesting actor"),
):
    """Download a completed export with audit logging."""
    export = _exports.get(export_id)
    if not export:
        audit.record(
            action="export.download",
            actor=actor,
            target_id=export_id,
            target_type="export",
            result="failure",
            metadata={"reason": "export_not_found"},
        )
        raise HTTPException(status_code=404, detail="Export not found")

    audit.record(
        action="export.download",
        actor=actor,
        target_id=export_id,
        target_type="export",
        result="success",
        metadata={"export_type": export["type"]},
    )
    return {
        "export_id": export_id,
        "type": export["type"],
        "content": f"Mock export data for {export_id}",
    }


@router.get("/exports")
async def list_exports():
    """List all exports."""
    return {"exports": list(_exports.values())}


@router.get("/audit/events")
async def get_audit_events(
    actor: Optional[str] = None,
    target_type: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    """Query audit trail events."""
    return {
        "events": audit.query(
            actor=actor, target_type=target_type, action=action, limit=limit
        )
    }
