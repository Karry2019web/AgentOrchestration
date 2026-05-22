"""Agent Registry — Manages agent lifecycle and metadata with handler version enforcement."""

import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from src.agent.handler_version import (
    HandlerVersionRegistry,
    HandlerVersionError,
    SemVer,
)

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._handler_registry = HandlerVersionRegistry()

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None,
                 version: str = "1.0.0") -> str:
        """Register a new agent with version validation.

        Args:
            name: Agent name.
            agent_type: Type identifier (e.g. 'worker.processor').
            config: Optional configuration dict.
            version: Agent/handler version string (semver).

        Returns:
            The generated agent ID.

        Raises:
            HandlerVersionError: If the version string is invalid.
        """
        semver = SemVer.parse(version)
        if semver.major == 0 and semver.minor == 0 and semver.patch == 0:
            raise HandlerVersionError(
                f"Invalid version '{version}' for agent '{name}': "
                "could not be parsed or version is 0.0.0"
            )

        agent_id = str(uuid.uuid4())
        timestamp = time.time()

        # Register handler version for compatibility tracking
        self._handler_registry.register(
            name=name,
            version_str=version,
            handler_type=agent_type,
            metadata={"agent_id": agent_id},
        )

        self._agents[agent_id] = {
            "id": agent_id,
            "name": name,
            "type": agent_type,
            "version": version,
            "status": AgentStatus.PENDING.value,
            "config": config or {},
            "created_at": timestamp,
            "updated_at": timestamp,
            "metrics": {"tasks_completed": 0, "errors": 0, "uptime": 0},
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)
        logger.info(f"Registered agent '{name}' (id: {agent_id}, version: {version})")
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        return self._agents.get(agent_id)

    def list(self, status: Optional[AgentStatus] = None, group: Optional[str] = None) -> List[Dict[str, Any]]:
        agents = list(self._agents.values())
        if status:
            agents = [a for a in agents if a["status"] == status.value]
        if group:
            agent_ids = self._index.get(group, [])
            agents = [a for a in agents if a["id"] in agent_ids]
        return agents

    def update_status(self, agent_id: str, status: AgentStatus) -> bool:
        if agent_id not in self._agents:
            return False
        self._agents[agent_id]["status"] = status.value
        self._agents[agent_id]["updated_at"] = time.time()
        return True

    def update_version(self, agent_id: str, new_version: str) -> bool:
        """Update an agent's version with compatibility validation.

        Validates that the version upgrade does not introduce breaking changes
        before applying the update. On success, cached handler resolutions are
        invalidated automatically.

        Args:
            agent_id: The agent to update.
            new_version: The new version string (semver).

        Returns:
            True if the version was updated.

        Raises:
            HandlerVersionError: If the upgrade introduces breaking changes.
            ValueError: If the agent is not found.
        """
        if agent_id not in self._agents:
            raise ValueError(f"Agent not found: {agent_id}")

        agent = self._agents[agent_id]
        old_version = agent["version"]

        # Validate the upgrade path
        is_safe, reason = self._handler_registry.validate_upgrade(
            agent["name"], old_version, new_version
        )
        if not is_safe:
            raise HandlerVersionError(
                f"Cannot upgrade agent '{agent['name']}' from {old_version} to {new_version}: {reason}"
            )

        # Apply the version update
        agent["version"] = new_version
        agent["updated_at"] = time.time()

        # Re-register with new version (invalidates caches)
        self._handler_registry.register(
            name=agent["name"],
            version_str=new_version,
            handler_type=agent["type"],
            metadata={"agent_id": agent_id, "upgraded_from": old_version},
        )

        logger.info(
            f"Updated agent '{agent['name']}' (id: {agent_id}) "
            f"version {old_version} -> {new_version}: {reason}"
        )
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        # Invalidate handler caches for this agent's name
        self._handler_registry.invalidate_handler(agent["name"])
        logger.info(f"Deleted agent '{agent['name']}' (id: {agent_id})")
        return True

    def count(self) -> int:
        return len(self._agents)

    def get_handler_registry(self) -> HandlerVersionRegistry:
        """Expose the handler version registry for inspection."""
        return self._handler_registry

    def resolve_handler(self, name: str, version_constraint: Optional[str] = None) -> Optional[str]:
        """Resolve an agent/handler by name with version constraint.

        Uses the handler version registry's cached resolution mechanism.
        Returns the agent ID if found, None otherwise.

        Args:
            name: Handler/agent name.
            version_constraint: Optional version constraint string.

        Returns:
            Agent ID of the best matching handler, or None.
        """
        handler = self._handler_registry.get_handler(name, version_constraint)
        if handler is None:
            return None
        agent_id = handler.metadata.get("agent_id")
        if agent_id and agent_id in self._agents:
            return agent_id
        return None
