"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.audit import audit_trail

router = APIRouter()
registry = AgentRegistry()


# In-memory export store
_exports: Dict[str, dict] = {}


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


# --- Export endpoints with audit trail ---

@router.post("/exports")
async def create_export(actor: str = "unknown"):
    """Create a new export and return a download token."""
    import uuid
    import datetime
    export_id = str(uuid.uuid4())
    _exports[export_id] = {
        "id": export_id,
        "status": "completed",
        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "created_by": actor,
    }
    return {"export_id": export_id, "download_url": f"/exports/{export_id}/download"}


@router.get("/exports/{export_id}/download")
async def download_export(export_id: str, actor: str = "unknown"):
    """Download an export, recording access in the audit trail."""
    export = _exports.get(export_id)
    if not export:
        audit_trail.record_download(
            actor=actor,
            export_id=export_id,
            success=False,
            error="Export not found",
        )
        raise HTTPException(status_code=404, detail="Export not found")

    try:
        audit_trail.record_download(
            actor=actor,
            export_id=export_id,
            success=True,
        )
        return {
            "export_id": export_id,
            "data": export,
            "content_type": "application/json",
        }
    except Exception as e:
        audit_trail.record_download(
            actor=actor,
            export_id=export_id,
            success=False,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Download failed")


@router.get("/exports/{export_id}/audit")
async def get_export_audit(export_id: str):
    """Get audit trail for a specific export."""
    events = audit_trail.get_events(export_id=export_id)
    return {"export_id": export_id, "events": events}


@router.get("/audit/exports")
async def list_audit_events(actor: Optional[str] = None, limit: int = 100):
    """List export audit events, optionally filtered by actor."""
    events = audit_trail.get_events(actor=actor, limit=limit)
    return {"events": events}
