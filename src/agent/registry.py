"""Agent Registry — Manages agent lifecycle and metadata."""

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from src.common.errors import (
    AgentNotFoundError,
    IncompatibleProtocolError,
    ProtocolNegotiationError,
)

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentProtocolVersion(Enum):
    """Supported agent RPC protocol versions. Higher = newer."""
    V1_0 = "1.0"
    V1_1 = "1.1"
    V2_0 = "2.0"

    @classmethod
    def current(cls) -> "AgentProtocolVersion":
        """Return the system's current protocol version."""
        return cls.V2_0

    @classmethod
    def compatible_versions(cls) -> Set["AgentProtocolVersion"]:
        """Return all versions compatible with the current system protocol."""
        current = cls.current()
        return {v for v in cls if cls._is_compatible(v, current)}

    @staticmethod
    def _is_compatible(agent_version: "AgentProtocolVersion",
                       system_version: "AgentProtocolVersion") -> bool:
        """Check if an agent version is compatible with the system version.

        Compatibility rules:
        - Same version → compatible
        - Agent version one major step behind → compatible (backward compatible)
        - Agent version ahead → compatible only if major is same (forward compatible within major)
        - Agent version two+ majors behind → incompatible
        """
        agent_parts = [int(x) for x in agent_version.value.split(".")]
        system_parts = [int(x) for x in system_version.value.split(".")]

        agent_major, agent_minor = agent_parts
        sys_major, sys_minor = system_parts

        # Exact match
        if agent_major == sys_major and agent_minor == sys_minor:
            return True

        # Agent ahead within same major series (forward compatible)
        if agent_major == sys_major and agent_minor > sys_minor:
            return True

        # Agent one major behind (backward compatible, e.g. V1.x → V2.0)
        if agent_major == sys_major - 1:
            return True

        # Agent more than one major behind → incompatible
        if agent_major <= sys_major - 2:
            return False

        # Agent ahead by one or more majors → incompatible
        if agent_major > sys_major and agent_major != sys_major:
            return False

        return False

    def __ge__(self, other):
        if self.__class__ is other.__class__:
            return self._to_int() >= other._to_int()
        return NotImplemented

    def _to_int(self) -> int:
        parts = [int(x) for x in self.value.split(".")]
        return parts[0] * 10000 + parts[1]


class ProtocolNegotiator:
    """Handles agent RPC protocol negotiation during registration and resolution."""

    def __init__(self):
        self._system_version = AgentProtocolVersion.current()
        self._compatible_cache: Dict[str, bool] = {}

    def validate_protocol(self, agent_id: str, version: str) -> None:
        """Validate that an agent's protocol version is compatible.

        Raises:
            IncompatibleProtocolError: if the version is incompatible.
            ProtocolNegotiationError: if the version string is malformed.
        """
        try:
            agent_version = AgentProtocolVersion(version)
        except ValueError:
            raise ProtocolNegotiationError(
                agent_id, version,
                f"Unknown protocol version '{version}'. "
                f"Supported versions: {[v.value for v in AgentProtocolVersion]}"
            ) from None

        if not AgentProtocolVersion._is_compatible(agent_version, self._system_version):
            raise IncompatibleProtocolError(
                agent_id=agent_id,
                agent_version=version,
                system_version=self._system_version.value,
            )

        # Cache the compatibility
        self._compatible_cache[agent_id] = True

    def invalidate_cache(self, agent_id: Optional[str] = None) -> None:
        """Invalidate protocol compatibility cache entries.

        Args:
            agent_id: If provided, invalidate only this agent's cache entry.
                      If None, invalidate all entries.
        """
        if agent_id:
            self._compatible_cache.pop(agent_id, None)
        else:
            self._compatible_cache.clear()

    def is_version_compatible(self, agent_version: str) -> bool:
        """Check if a version string is compatible without raising.

        Returns True if compatible, False otherwise.
        """
        try:
            av = AgentProtocolVersion(agent_version)
            return AgentProtocolVersion._is_compatible(av, self._system_version)
        except (ValueError, KeyError):
            return False

    @property
    def system_version(self) -> str:
        return self._system_version.value


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._negotiator = ProtocolNegotiator()

    def register(self, name: str, agent_type: str,
                 config: Optional[Dict] = None,
                 protocol_version: Optional[str] = None) -> str:
        """Register a new agent with protocol version validation.

        Args:
            name: Agent display name.
            agent_type: Type identifier (e.g. "worker.processor").
            config: Optional configuration dict.
            protocol_version: Agent's protocol version string.
                             If None, defaults to the current system version.

        Returns:
            The assigned agent ID.

        Raises:
            IncompatibleProtocolError: if the agent's protocol version
                                       is incompatible with the system.
            ProtocolNegotiationError: if the version string is malformed.
        """
        if protocol_version is None:
            protocol_version = AgentProtocolVersion.current().value

        # Validate protocol compatibility before registering
        self._negotiator.validate_protocol("new-agent", protocol_version)

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
            "version": protocol_version,
            "protocol_version": protocol_version,
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(self, status: Optional[AgentStatus] = None,
             group: Optional[str] = None,
             min_protocol_version: Optional[str] = None) -> List[Dict[str, Any]]:
        """List agents with optional protocol version filtering.

        Args:
            status: Optional status filter.
            group: Optional group filter.
            min_protocol_version: If set, only return agents whose protocol
                                  version is >= this value.

        Returns:
            List of matching agent dicts.
        """
        agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        if min_protocol_version:
            try:
                min_v = AgentProtocolVersion(min_protocol_version)
                agents = [
                    a for a in agents
                    if AgentProtocolVersion(a.get("protocol_version", a.get("version", "1.0"))) >= min_v
                ]
            except ValueError:
                logger.warning("Invalid min_protocol_version filter: %s", min_protocol_version)
        return agents

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def update_protocol(self, agent_id: str, new_version: str) -> bool:
        """Update an agent's protocol version after validation.

        Invalidates the compatibility cache for this agent.

        Args:
            agent_id: The agent to update.
            new_version: The new protocol version string.

        Returns:
            True if the update succeeded.

        Raises:
            AgentNotFoundError: if the agent_id does not exist.
            IncompatibleProtocolError: if the new version is incompatible.
            ProtocolNegotiationError: if the version string is malformed.
        """
        if agent_id not in self._agents:
            raise AgentNotFoundError(agent_id)

        self._negotiator.validate_protocol(agent_id, new_version)
        self._agents[agent_id]["protocol_version"] = new_version
        self._agents[agent_id]["version"] = new_version
        self._agents[agent_id]["updated_at"] = time.time()
        self._negotiator.invalidate_cache(agent_id)
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        self._negotiator.invalidate_cache(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    @property
    def negotiator(self) -> ProtocolNegotiator:
        return self._negotiator
