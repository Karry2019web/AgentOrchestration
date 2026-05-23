"""Agent Registry — Manages agent lifecycle and metadata with capability contract enforcement."""

import hashlib
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


class CapabilityContract:
    """Tracks capability schema version for agents and enables cache invalidation."""

    def __init__(self, schema: Optional[Dict[str, Any]] = None):
        self._schema = schema or {}
        self._version: int = 1
        self._contract_hash: str = self._compute_hash(self._schema)

    @staticmethod
    def _compute_hash(schema: Dict[str, Any]) -> str:
        raw = json.dumps(schema, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def version(self) -> int:
        return self._version

    @property
    def contract_hash(self) -> str:
        return self._contract_hash

    def update_schema(self, new_schema: Dict[str, Any]) -> bool:
        """Update the capability schema. Returns True if the contract changed."""
        new_hash = self._compute_hash(new_schema)
        if new_hash == self._contract_hash:
            return False
        self._schema = new_schema
        self._version += 1
        self._contract_hash = new_hash
        return True

    def get_schema(self) -> Dict[str, Any]:
        return dict(self._schema)


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._capability_contract = CapabilityContract()
        self._agent_contract_versions: Dict[str, int] = {}
        self._version_agents: Dict[int, List[str]] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        contract_version = self._capability_contract.version
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
            "_contract_version": contract_version,
        }
        self._agent_contract_versions[agent_id] = contract_version
        if contract_version not in self._version_agents:
            self._version_agents[contract_version] = []
        self._version_agents[contract_version].append(agent_id)

        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent, returning None if its contract version is stale."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        if not self._is_contract_current(agent_id):
            return None
        return agent

    def get_or_invalidate(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get agent, invalidating stale cache entries on access."""
        agent = self._agents.get(agent_id)
        if agent is None:
            return None
        if not self._is_contract_current(agent_id):
            self.invalidate(agent_id)
            return None
        return agent

    def _is_contract_current(self, agent_id: str) -> bool:
        agent = self._agents.get(agent_id)
        if agent is None:
            return True
        return agent.get("_contract_version", 0) == self._capability_contract.version

    def list(self, status: Optional[AgentStatus] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
        agents = list(self._agents.values())
        agents = [a for a in agents if self._is_contract_current(a["id"])]
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = set(self._index.get(group, []))
            agents = [a for a in agents if a["id"] in agent_ids]
        return list(agents)

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        if not self._is_contract_current(agent_id):
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def update_contract_schema(self, new_schema: Dict[str, Any]) -> bool:
        """Update the capability contract. Returns True if anything changed."""
        changed = self._capability_contract.update_schema(new_schema)
        if changed:
            self._version_agents[self._capability_contract.version] = []
        return changed

    def invalidate(self, agent_id: str) -> bool:
        """Invalidate a specific agent's cached entry."""
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._agent_contract_versions.pop(agent_id, None)
        return True

    def invalidate_stale(self) -> int:
        """Invalidate all agents with stale contract versions. Returns count."""
        stale = [
            aid for aid in list(self._agents.keys())
            if not self._is_contract_current(aid)
        ]
        for aid in stale:
            self.invalidate(aid)
        return len(stale)

    def invalidate_all(self) -> int:
        """Invalidate all cached agents. Returns the count invalidated."""
        count = len(self._agents)
        self._agents.clear()
        self._index.clear()
        self._agent_contract_versions.clear()
        self._version_agents.clear()
        self._version_agents[self._capability_contract.version] = []
        return count

    def get_contract_version(self) -> int:
        return self._capability_contract.version

    def get_contract_hash(self) -> str:
        return self._capability_contract.contract_hash

    def get_contract_schema(self) -> Dict[str, Any]:
        return self._capability_contract.get_schema()

    def count(self) -> int:
        return len([a for a in self._agents if self._is_contract_current(a)])
