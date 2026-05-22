"""Agent Registry — Manages agent lifecycle and metadata."""

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


class VersionError(ValueError):
    """Raised when a handler version is incompatible with its agent."""


class HandlerVersion:
    """Semantic version comparison for handler compatibility."""

    def __init__(self, version: str):
        parts = version.split(".")
        self.major = int(parts[0]) if len(parts) > 0 else 0
        self.minor = int(parts[1]) if len(parts) > 1 else 0
        self.patch = int(parts[2]) if len(parts) > 2 else 0

    def is_compatible_with(self, other: "HandlerVersion") -> bool:
        """Return True if this version is compatible with *other*.
        
        Compatibility rules:
        - Same major version is always compatible.
        - Major version 0 (pre-release) requires exact match.
        """
        if self.major == 0 or other.major == 0:
            return self.major == other.major and self.minor == other.minor
        return self.major == other.major

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HandlerVersion):
            return NotImplemented
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        # Track handler version policies per agent group
        self._version_policies: Dict[str, str] = {}
        # Cache for handler resolution — invalidated on version changes
        self._handler_cache: Dict[str, str] = {}

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None,
                 handler_version: Optional[str] = None) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        
        # Validate handler version compatibility if provided
        if handler_version is not None:
            self._validate_handler_version(agent_type, handler_version)
        
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": handler_version or "1.0.0",
            "handler_version": handler_version,
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def _validate_handler_version(self, agent_type: str, handler_version: str) -> None:
        """Validate that a handler version is compatible with existing agents of the same type.
        
        Raises VersionError if incompatible.
        """
        group = agent_type.split(".")[0]
        policy_version = self._version_policies.get(group)
        if policy_version is not None:
            incoming = HandlerVersion(handler_version)
            existing = HandlerVersion(policy_version)
            if not incoming.is_compatible_with(existing):
                raise VersionError(
                    f"Handler version {handler_version} is incompatible with "
                    f"existing policy version {policy_version} for group '{group}'. "
                    f"Major version must match (got {incoming.major}, "
                    f"expected {existing.major})."
                )

    def resolve_handler(self, agent_id: str, handler_version: str) -> Optional[str]:
        """Resolve a handler for *agent_id*, verifying version compatibility.
        
        Returns the agent_id if compatible, None otherwise.
        Caches results and invalidates on version policy changes.
        """
        cache_key = f"{agent_id}:{handler_version}"
        if cache_key in self._handler_cache:
            return self._handler_cache[cache_key]

        agent = self._agents.get(agent_id)
        if not agent:
            return None

        incoming = HandlerVersion(handler_version)
        registered = HandlerVersion(agent.get("handler_version") or agent.get("version", "1.0.0"))
        
        result = None
        if incoming.is_compatible_with(registered):
            result = agent_id
        
        self._handler_cache[cache_key] = result
        return result

    def set_version_policy(self, group: str, version: str) -> None:
        """Set the minimum compatible version policy for a group.
        
        Invalidates the handler cache for all agents in the group.
        """
        self._version_policies[group] = version
        # Invalidate cache entries for this group
        self._handler_cache = {
            k: v for k, v in self._handler_cache.items()
            if not k.startswith(tuple(self._index.get(group, [])))
        }

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

    def update_handler_version(self, agent_id: str, new_version: str) -> bool:
        """Update the handler version for an agent with compatibility check.
        
        Invalidates cached resolutions for this agent.
        Returns True if the update was applied.
        """
        if agent_id not in self._agents:
            return False
        
        agent = self._agents[agent_id]
        group = agent["type"].split(".")[0]
        
        # Validate against group policy
        self._validate_handler_version(agent["type"], new_version)
        
        old_version = agent.get("handler_version") or agent.get("version", "1.0.0")
        agent["handler_version"] = new_version
        agent["version"] = new_version
        agent["updated_at"] = time.time()
        
        # Invalidate cache entries for this agent
        self._handler_cache = {
            k: v for k, v in self._handler_cache.items()
            if not k.startswith(agent_id)
        }
        
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        # Invalidate cache entries for this agent
        self._handler_cache = {
            k: v for k, v in self._handler_cache.items()
            if not k.startswith(agent_id)
        }
        return True

    def count(self) -> int:
        return len(self._agents)
