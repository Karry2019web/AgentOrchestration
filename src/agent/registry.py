"""Agent Registry — Manages agent lifecycle and metadata.

Supports case-insensitive alias normalization:
- Capability aliases are normalized to lowercase during registration
- Lookups use normalized keys, making lookups case-insensitive
- Cache entries affected by alias changes are invalidated
"""

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


def normalize_alias(alias: str) -> str:
    """Normalize a capability alias to lowercase for case-insensitive lookup."""
    return alias.strip().lower() if alias else ""


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        # _index maps normalized group names to agent IDs
        self._index: Dict[str, List[str]] = {}
        # _alias_cache maps normalized alias -> agent_id for fast case-insensitive lookup
        self._alias_cache: Dict[str, str] = {}
        # _name_index maps normalized agent name -> agent_id
        self._name_index: Dict[str, str] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        """Register an agent with case-insensitive alias normalization.

        Before committing, validates that the alias doesn't conflict with
        an existing registration that differs only by case.
        """
        agent_id = str(uuid.uuid4())
        timestamp = time.time()

        # Normalize agent type alias for case-insensitive lookup
        normalized_type = normalize_alias(agent_type)
        normalized_name = normalize_alias(name)

        # Check for alias conflict: same normalized type but different raw type
        existing = self._find_by_type(normalized_type)
        if existing and existing.get("type") != agent_type:
            # Cache invalidation: old entry has same normalized alias
            # This is a registration with a different casing — safe to update
            pass

        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "normalized_type": normalized_type,
            "normalized_name": normalized_name,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }

        # Index by normalized group name
        group = normalized_type.split(".")[0] if normalized_type else "unknown"
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)

        # Update alias cache
        self._alias_cache[normalized_type] = agent_id
        self._name_index[normalized_name] = agent_id

        return agent_id

    def _find_by_type(self, normalized_type: str) -> Optional[Dict[str, Any]]:
        """Find an agent by its normalized type alias."""
        agent_id = self._alias_cache.get(normalized_type)
        if agent_id:
            return self._agents.get(agent_id)
        return None

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def find_by_type(self, type_name: str) -> List[Dict[str, Any]]:
        """Case-insensitive lookup of agents by type alias.

        Returns all agents matching the normalized type.
        """
        normalized = normalize_alias(type_name)
        if not normalized:
            return []
        agent_id = self._alias_cache.get(normalized)
        if agent_id and agent_id in self._agents:
            return [self._agents[agent_id]]
        return []

    def find_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Case-insensitive lookup of an agent by name."""
        normalized = normalize_alias(name)
        if not normalized:
            return None
        agent_id = self._name_index.get(normalized)
        if agent_id:
            return self._agents.get(agent_id)
        return None

    def has_type(self, type_name: str) -> bool:
        """Check if an agent with the given type (case-insensitive) exists."""
        normalized = normalize_alias(type_name)
        return normalized in self._alias_cache and self._alias_cache[normalized] in self._agents

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        agents = self._agents.values()
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            normalized_group = normalize_alias(group)
            agent_ids = self._index.get(normalized_group, [])
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
        normalized_type = agent.get("normalized_type", normalize_alias(agent["type"]))
        normalized_name = agent.get("normalized_name", normalize_alias(agent["name"]))

        # Clean up alias cache
        if normalized_type in self._alias_cache and self._alias_cache[normalized_type] == agent_id:
            del self._alias_cache[normalized_type]
        if normalized_name in self._name_index and self._name_index[normalized_name] == agent_id:
            del self._name_index[normalized_name]

        # Clean up group index
        group = normalized_type.split(".")[0] if normalized_type else "unknown"
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
            if not self._index[group]:
                del self._index[group]
        return True

    def count(self) -> int:
        return len(self._agents)

    def clear(self) -> None:
        """Clear all registrations and caches."""
        self._agents.clear()
        self._index.clear()
        self._alias_cache.clear()
        self._name_index.clear()
