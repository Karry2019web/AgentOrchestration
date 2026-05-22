"""Agent Registry — Manages agent lifecycle, metadata, and protocol negotiation."""

import json
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class RouteWeightPolicy:
    """Manages traffic splitting route weights and validates their totals."""

    def __init__(self):
        self._routes: Dict[str, Dict[str, int]] = {}

    def set_weights(self, routing_key: str, weights: Dict[str, int]) -> None:
        """Set route weights for a given routing key after validation."""
        error = self._validate_weights(routing_key, weights)
        if error:
            raise ValueError(error)
        self._routes[routing_key] = dict(weights)

    def get_weights(self, routing_key: str) -> Optional[Dict[str, int]]:
        return self._routes.get(routing_key)

    def _validate_weights(self, routing_key: str, weights: Dict[str, int]) -> Optional[str]:
        """Validate route weight totals.
        
        Returns an error message if invalid, None if valid.
        
        Rules:
        - At least one route must be defined.
        - Each weight must be a positive integer.
        - Total weight must equal 100.
        - No duplicate route entries.
        """
        if not weights:
            return f"Route weights for '{routing_key}' must not be empty"

        if len(weights) < 1:
            return f"Route weights for '{routing_key}' must have at least one target"

        total = 0
        seen = set()
        for route, weight in weights.items():
            if route in seen:
                return f"Duplicate route '{route}' in routing key '{routing_key}'"
            seen.add(route)

            if not isinstance(weight, int) or weight < 0:
                return f"Weight for route '{route}' must be a non-negative integer, got {weight}"

            total += weight

        if total != 100:
            return (
                f"Route weights for '{routing_key}' must total 100, "
                f"got {total} (weights: {weights})"
            )

        return None

    def list_routing_keys(self) -> List[str]:
        return list(self._routes.keys())

    def clear(self) -> None:
        self._routes.clear()


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._route_policy = RouteWeightPolicy()

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(self, status: Optional[AgentStatus] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def set_route_weights(self, routing_key: str, weights: Dict[str, int]) -> None:
        """Set route weights for traffic splitting, with validation."""
        self._route_policy.set_weights(routing_key, weights)

    def get_route_weights(self, routing_key: str) -> Optional[Dict[str, int]]:
        return self._route_policy.get_weights(routing_key)

    @property
    def route_policy(self) -> RouteWeightPolicy:
        return self._route_policy

# 2026-05-22T12:10:26 update - added RouteWeightPolicy for traffic splitting validation
