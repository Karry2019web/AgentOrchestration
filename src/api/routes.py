"""API route definitions."""

from fastapi import APIRouter, HTTPException, Depends
from typing import Any, Dict, List, Optional

from src.agent import AgentRegistry, AgentStatus
from src.common.queries import TraceQueryGuard, QueryFilterDepthError

router = APIRouter()
registry = AgentRegistry()
trace_query_guard = TraceQueryGuard()

# Sample trace store (in-memory for trace explorer queries)
_trace_store: List[Dict[str, Any]] = [
    {"trace_id": "trace-001", "agent_id": "agent-alpha", "action": "process", "status": "completed", "duration_ms": 120, "tags": {"env": "prod", "region": "us-east"}},
    {"trace_id": "trace-002", "agent_id": "agent-beta", "action": "deploy", "status": "failed", "duration_ms": 4500, "tags": {"env": "staging", "region": "us-west"}},
    {"trace_id": "trace-003", "agent_id": "agent-alpha", "action": "infer", "status": "completed", "duration_ms": 890, "tags": {"env": "prod", "region": "eu-west"}},
    {"trace_id": "trace-004", "agent_id": "agent-gamma", "action": "train", "status": "running", "duration_ms": 12200, "tags": {"env": "dev", "region": "us-east"}},
    {"trace_id": "trace-005", "agent_id": "agent-beta", "action": "rollback", "status": "completed", "duration_ms": 2400, "tags": {"env": "prod", "region": "ap-southeast"}},
]


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


# --- Trace Query API with nested filter depth guard ---


@router.post("/traces/query")
async def query_traces(filters: Optional[Dict[str, Any]] = None, limit: int = 100):
    """Query traces with optional filter criteria.

    Filters use a MongoDB-style query syntax:
      {"agent_id": "agent-alpha", "status": "completed"}
      {"$and": [{"duration_ms": {"$gt": 1000}}, {"status": "failed"}]}
      {"duration_ms": {"$gte": 100, "$lte": 5000}}

    The nested filter depth is guarded at 5 levels maximum.
    """
    if filters:
        try:
            trace_query_guard.validate(filters)
        except QueryFilterDepthError as e:
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "FILTER_DEPTH_EXCEEDED",
                    "message": str(e),
                    "depth": e.depth,
                    "max_depth": e.max_depth,
                }
            )

    results = _query_trace_store(filters or {}, limit=limit)
    return {"traces": results, "count": len(results)}


@router.get("/traces")
async def list_traces(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    action: Optional[str] = None,
    limit: int = 100,
):
    """List traces with simple query parameter filters (no nesting guard needed)."""
    filters = {}
    if agent_id:
        filters["agent_id"] = agent_id
    if status:
        filters["status"] = status
    if action:
        filters["action"] = action

    results = _query_trace_store(filters, limit=limit)
    return {"traces": results, "count": len(results)}


def _match_trace(trace: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """Apply MongoDB-style filters to a single trace record.

    Supports:
      - Field equality: {"agent_id": "agent-alpha"}
      - Comparison operators: $gt, $gte, $lt, $lte, $ne, $eq
      - Logical operators: $and, $or, $not
      - List matching ($in, $nin)
    """
    for field, condition in filters.items():
        if field == "$and":
            if not all(_match_trace(trace, sub) for sub in condition):
                return False
        elif field == "$or":
            if not any(_match_trace(trace, sub) for sub in condition):
                return False
        elif field == "$not":
            if _match_trace(trace, condition):
                return False
        elif isinstance(condition, dict):
            actual = _get_nested_field(trace, field)
            for op, val in condition.items():
                if op == "$gt" and not (actual is not None and actual > val):
                    return False
                elif op == "$gte" and not (actual is not None and actual >= val):
                    return False
                elif op == "$lt" and not (actual is not None and actual < val):
                    return False
                elif op == "$lte" and not (actual is not None and actual <= val):
                    return False
                elif op == "$ne" and not (actual is not None and actual != val):
                    return False
                elif op == "$eq" and actual != val:
                    return False
                elif op == "$in" and (actual is None or actual not in val):
                    return False
                elif op == "$nin" and (actual is not None and actual in val):
                    return False
                elif op not in ("$gt", "$gte", "$lt", "$lte", "$ne", "$eq", "$in", "$nin"):
                    return False
        else:
            actual = _get_nested_field(trace, field)
            if actual != condition:
                return False
    return True


def _get_nested_field(obj: Dict[str, Any], dotted_path: str) -> Any:
    """Access a nested field by dotted path (e.g. 'tags.env')."""
    parts = dotted_path.split(".")
    current = obj
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _query_trace_store(filters: Dict[str, Any], limit: int = 100) -> List[Dict[str, Any]]:
    """Query the in-memory trace store with optional filters."""
    filtered = [t for t in _trace_store if _match_trace(t, filters)]
    return filtered[:limit]


# 2019-03-18T11:10:18 update

# 2019-04-22T13:58:05 update

# 2019-05-28T08:52:40 update

# 2019-06-13T19:27:11 update

# 2019-06-25T18:52:04 update

# 2019-06-26T17:23:40 update

# 2019-07-24T12:38:12 update

# 2019-08-06T17:13:22 update

# 2019-09-26T19:27:40 update

# 2019-11-08T15:48:07 update

# 2019-12-05T16:07:01 update

# 2020-01-17T17:50:06 update

# 2020-04-24T17:12:53 update

# 2020-07-21T19:32:14 update

# 2020-07-21T20:23:54 update

# 2020-08-14T20:37:18 update

# 2020-11-05T16:47:32 update

# 2021-03-11T12:52:51 update

# 2021-03-15T12:40:28 update

# 2021-03-19T19:24:45 update

# 2021-05-07T14:43:25 update

# 2021-05-12T12:11:05 update

# 2021-05-26T19:45:39 update

# 2021-06-29T19:14:28 update

# 2021-07-09T17:57:49 update

# 2021-07-19T08:20:34 update

# 2021-07-23T15:35:00 update

# 2021-07-26T09:55:35 update

# 2021-11-01T20:50:23 update

# 2022-02-04T09:23:08 update

# 2022-02-14T15:58:17 update

# 2022-02-28T09:52:05 update

# 2022-05-19T16:28:06 update

# 2022-05-30T15:01:44 update

# 2022-07-31T11:24:57 update

# 2022-08-09T15:47:57 update

# 2022-08-19T12:51:59 update

# 2022-11-02T08:06:45 update

# 2022-11-21T14:12:56 update

# 2023-01-13T12:25:51 update

# 2023-03-31T14:11:34 update

# 2023-04-03T20:57:22 update

# 2023-04-28T19:01:38 update

# 2023-07-18T16:47:22 update

# 2023-09-28T18:50:58 update

# 2023-10-02T13:22:15 update

# 2023-10-23T10:46:19 update

# 2023-11-02T16:52:55 update

# 2023-12-08T17:38:20 update

# 2023-12-11T10:59:19 update

# 2024-01-15T16:27:41 update

# 2024-02-09T11:56:21 update

# 2024-02-15T16:47:43 update

# 2024-03-26T08:08:33 update

# 2024-07-11T15:59:46 update

# 2024-09-04T17:13:05 update

# 2024-09-20T11:28:38 update

# 2024-12-02T16:42:53 update

# 2025-01-15T12:12:38 update

# 2025-02-05T09:08:36 update

# 2025-05-16T19:40:31 update

# 2025-06-13T13:20:50 update

# 2025-08-13T12:22:26 update

# 2025-09-01T12:30:44 update

# 2025-11-06T12:23:44 update

# 2025-12-26T08:40:45 update

# 2026-04-08T19:23:48 update

# 2026-04-09T20:30:37 update

# 2026-05-13T11:36:25 update

