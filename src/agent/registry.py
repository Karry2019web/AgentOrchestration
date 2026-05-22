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


class ProtocolVersion:
    """Represents a semantic protocol version for agent RPC negotiation."""

    def __init__(self, major: int, minor: int, patch: int = 0):
        self.major = major
        self.minor = minor
        self.patch = patch

    @classmethod
    def parse(cls, version_str: str) -> "ProtocolVersion":
        parts = version_str.strip().split(".")
        major = int(parts[0]) if len(parts) > 0 else 0
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0
        return cls(major, minor, patch)

    def is_compatible_with(self, other: "ProtocolVersion") -> bool:
        """Check if this version is compatible with another.
        
        Compatibility rule: same major version required; minor and patch
        can be equal or higher (backward compatible within major version).
        """
        return self.major == other.major and self.minor >= other.minor

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    def __eq__(self, other):
        if not isinstance(other, ProtocolVersion):
            return False
        return (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)

    def __repr__(self):
        return f"ProtocolVersion({self.major}, {self.minor}, {self.patch})"


# Default protocol version for the current system
CURRENT_PROTOCOL = ProtocolVersion(2, 1, 0)
# Minimum supported protocol version
MINIMUM_PROTOCOL = ProtocolVersion(2, 0, 0)


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._cache: Dict[str, Any] = {}
        self._cache_version: int = 0
        self._negotiated_protocols: Dict[str, str] = {}

    def _validate_protocol(self, protocol_version: Optional[str]) -> Optional[str]:
        """Validate and check protocol version compatibility.
        
        Returns an error message if incompatible, None if valid.
        """
        if protocol_version is None:
            return "Protocol version is required for agent RPC negotiation"

        try:
            version = ProtocolVersion.parse(protocol_version)
        except (ValueError, AttributeError):
            return f"Invalid protocol version format: {protocol_version!r}"

        if not version.is_compatible_with(MINIMUM_PROTOCOL):
            return (
                f"Incompatible protocol version {version}. "
                f"Minimum required: {MINIMUM_PROTOCOL} "
                f"(current: {CURRENT_PROTOCOL})"
            )

        if version.major != CURRENT_PROTOCOL.major:
            return (
                f"Protocol major version mismatch: {version.major} != {CURRENT_PROTOCOL.major}. "
                f"Agent uses protocol {version}, system requires protocol {CURRENT_PROTOCOL.major}.x"
            )

        return None

    def _invalidate_cache(self) -> None:
        """Invalidate all cached entries affected by protocol or registration changes."""
        self._cache_version += 1
        self._cache.clear()
        self._negotiated_protocols.clear()

    def register(
        self,
        name: str,
        agent_type: str,
        config: Optional[Dict] = None,
        protocol_version: Optional[str] = None,
    ) -> str:
        # Validate protocol version before registration
        protocol_error = self._validate_protocol(protocol_version)
        if protocol_error:
            raise ValueError(f"Cannot register agent: {protocol_error}")

        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "protocol_version": protocol_version or str(CURRENT_PROTOCOL),
            "created_at": timestamp,
            "updated_at": timestamp,
            "version": "1.0.0",
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)

        # Record negotiated protocol
        self._negotiated_protocols[agent_id] = protocol_version or str(CURRENT_PROTOCOL)

        # Invalidate cache entries affected by this registration
        self._invalidate_cache()

        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def resolve(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Resolve an agent for RPC, checking protocol compatibility.
        
        Returns the agent data if resolvable, or None if the agent is
        incompatible or doesn't exist.
        
        Also invalidates cache on resolution to ensure fresh state.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            self._invalidate_cache()
            return None

        # Verify the agent's protocol is still compatible at resolution time
        agent_protocol = agent.get("protocol_version", str(CURRENT_PROTOCOL))
        protocol_error = self._validate_protocol(agent_protocol)
        if protocol_error:
            agent["status"] = AgentStatus.FAILED.value
            agent["updated_at"] = time.time()
            self._invalidate_cache()
            return None

        # Update negotiated protocol
        self._negotiated_protocols[agent_id] = agent_protocol
        return agent

    def list(
        self,
        status: Optional[AgentStatus] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
        self._invalidate_cache()
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._negotiated_protocols.pop(agent_id, None)
        self._invalidate_cache()
        return True

    def count(self) -> int:
        return len(self._agents)

    def get_negotiated_protocol(self, agent_id: str) -> Optional[str]:
        """Get the negotiated protocol version for an agent."""
        return self._negotiated_protocols.get(agent_id)

    def get_cache_version(self) -> int:
        """Return the current cache version for external cache invalidation."""
        return self._cache_version

# 2026-05-22T12:10:26 update - added protocol negotiation with version validation and cache invalidation
