"""Agent Registry — Manages agent lifecycle and metadata with workspace-scoped access."""

import json
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


class AgentRegistry:
    """Agent registry with mandatory workspace-scoped access."""

    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._ws_index: Dict[str, List[str]] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None, workspace_id: str = "default") -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id, "name": name, "type": agent_type,
            "status": AgentStatus.PENDING.value, "config": config or {},
            "created_at": timestamp, "updated_at": timestamp,
            "version": "1.0.0", "workspace_id": workspace_id,
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        if workspace_id not in self._ws_index:
            self._ws_index[workspace_id] = []
        self._ws_index[workspace_id].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def get_scoped(self, agent_id: str, workspace_id: str) -> Optional[Dict[str, Any]]:
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        if agent.get("workspace_id") != workspace_id:
            return None
        return agent

    def list(self, status=None, group=None, workspace_id=None):
        agents = list(self._agents.values())
        if workspace_id is not None:
            ws_ids = set(self._ws_index.get(workspace_id, []))
            agents = [a for a in agents if a["id"] in ws_ids]
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = set(self._index.get(group, []))
            agents = [a for a in agents if a["id"] in agent_ids]
        return agents

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def update_status_scoped(self, agent_id: str, status: AgentStatus, workspace_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        if agent.get("workspace_id") != workspace_id:
            return False
        agent["status"] = status.value
        agent["updated_at"] = time.time()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        ws_id = agent.get("workspace_id", "default")
        if ws_id in self._ws_index and agent_id in self._ws_index[ws_id]:
            self._ws_index[ws_id].remove(agent_id)
        return True

    def delete_scoped(self, agent_id: str, workspace_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent is None:
            return False
        if agent.get("workspace_id") != workspace_id:
            return False
        return self.delete(agent_id)

    def count(self, workspace_id=None):
        if workspace_id is not None:
            return len(self._ws_index.get(workspace_id, []))
        return len(self._agents)
