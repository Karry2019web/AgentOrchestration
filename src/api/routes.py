"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.trace_query import TraceQueryService, TraceQueryError, NestedFilterDepthError

router = APIRouter()
registry = AgentRegistry()


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


@router.post("/traces/query")
async def query_traces(body: Dict):
    """Query traces with nested filter depth validation.

    Validates and executes trace queries, guarding against excessively
    nested filter structures that could cause stack exhaustion.
    """
    try:
        params = TraceQueryService.parse_and_validate_query(body)
    except NestedFilterDepthError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except TraceQueryError as e:
        raise HTTPException(status_code=422, detail=str(e))

    results = TraceQueryService.execute_query(params)
    return {
        "traces": results,
        "total": len(results),
        "query": {
            "trace_type": params["trace_type"],
            "limit": params["limit"],
            "offset": params["offset"],
        },
    }
