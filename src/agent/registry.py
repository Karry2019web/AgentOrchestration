"""Agent Registry — Manages agent lifecycle and metadata."""

import json
import re
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


_PATH_TRAVERSAL_PATTERN = re.compile(r"(?:^|[\\/])\.\.(?:[\\/]|$)")


def _validate_handler_name(name: str) -> None:
    """Validate a handler/agent name does not contain path traversal sequences.
    
    Args:
        name: The handler name to validate.
        
    Raises:
        ValueError: If the name contains path traversal sequences like "..", "../", or "..\\".
    """
    if not name or not isinstance(name, str):
        raise ValueError("Handler name must be a non-empty string")
    if _PATH_TRAVERSAL_PATTERN.search(name):
        raise ValueError(
            f"Handler name {name!r} contains path traversal sequences and is not allowed"
        )


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        _validate_handler_name(name)
        _validate_handler_name(agent_type)
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

    def resolve(self, name: str) -> Optional[Dict[str, Any]]:
        """Resolve an agent by handler name.
        
        Args:
            name: The handler name to resolve.
            
        Returns:
            The agent dict if found, None otherwise.
            
        Raises:
            ValueError: If the name contains path traversal sequences.
        """
        _validate_handler_name(name)
        for agent_id, agent in self._agents.items():
            if agent["name"] == name:
                return agent
        return None
