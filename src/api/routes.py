"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import List, Dict, Optional

from src.agent import AgentRegistry, AgentStatus
from src.orchestrator.engine import OrchestrationEngine
from src.orchestrator.canary import CanaryAnalyzer

router = APIRouter()
registry = AgentRegistry()
engine = OrchestrationEngine()


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


@router.get("/deploy/canary")
async def get_canary_status():
    """Run and return canary analysis results.

    Evaluates queue backlog, processing latency, lease renewal failures,
    and worker saturation to determine if a canary should be promoted.
    """
    decision = engine.run_canary_analysis()
    return decision


@router.get("/deploy/canary/metrics")
async def get_canary_metrics():
    """Return raw scheduler metrics for canary dashboards.

    Includes queue depth per queue, in-flight task counts,
    processing latency averages, and lease renewal stats.
    """
    metrics = engine.get_canary_metrics()
    return {
        "metrics": metrics,
        "worker_count": len(registry.list(status=AgentStatus.RUNNING)),
    }
