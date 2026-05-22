"""API route definitions with consistent error codes."""

from fastapi import APIRouter, HTTPException
from typing import Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.errors import error_response, ERROR_CODES

router = APIRouter()
registry = AgentRegistry()


@router.get("/agents")
async def list_agents(status: Optional[str] = None, group: Optional[str] = None):
    if status is not None:
        try:
            AgentStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=error_response(
                    status_code=422,
                    code=ERROR_CODES["VALIDATION_ERROR"],
                    message=f"Invalid agent status: '{status}'",
                    details={"allowed_values": [s.value for s in AgentStatus]},
                ),
            )
    status_filter = AgentStatus(status) if status else None
    return {"agents": registry.list(status=status_filter, group=group)}


@router.post("/agents")
async def register_agent(name: str, agent_type: str, config: Optional[Dict] = None):
    if not name or not name.strip():
        raise HTTPException(
            status_code=422,
            detail=error_response(
                status_code=422,
                code=ERROR_CODES["VALIDATION_ERROR"],
                message="Agent name must not be empty",
            ),
        )
    if not agent_type or not agent_type.strip():
        raise HTTPException(
            status_code=422,
            detail=error_response(
                status_code=422,
                code=ERROR_CODES["VALIDATION_ERROR"],
                message="Agent type must not be empty",
            ),
        )
    agent_id = registry.register(name, agent_type, config)
    return {"agent_id": agent_id, "status": "registered"}


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str):
    agent = registry.get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=error_response(
                status_code=404,
                code=ERROR_CODES["NOT_FOUND"],
                message=f"Agent not found: {agent_id}",
            ),
        )
    return agent


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    if not registry.delete(agent_id):
        raise HTTPException(
            status_code=404,
            detail=error_response(
                status_code=404,
                code=ERROR_CODES["NOT_FOUND"],
                message=f"Agent not found: {agent_id}",
            ),
        )
    return {"status": "deleted"}


@router.post("/agents/{agent_id}/start")
async def start_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.RUNNING):
        raise HTTPException(
            status_code=404,
            detail=error_response(
                status_code=404,
                code=ERROR_CODES["NOT_FOUND"],
                message=f"Agent not found: {agent_id}",
            ),
        )
    return {"status": "started"}


@router.post("/agents/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if not registry.update_status(agent_id, AgentStatus.PAUSED):
        raise HTTPException(
            status_code=404,
            detail=error_response(
                status_code=404,
                code=ERROR_CODES["NOT_FOUND"],
                message=f"Agent not found: {agent_id}",
            ),
        )
    return {"status": "stopped"}


@router.get("/agents/count")
async def agent_count():
    return {"count": registry.count()}
