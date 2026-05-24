"""Agent Registry — Manages agent lifecycle and metadata with authorization caching."""

import json
import logging
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    FAILED = "failed"
    TERMINATED = "terminated"


class AuthCacheEntry:
    """Represents a cached authorization check result for an agent resolution."""

    def __init__(self, agent_id: str, permissions_hash: str, resolver: str):
        self.agent_id = agent_id
        self.permissions_hash = permissions_hash
        self.resolver = resolver
        self.cached_at = time.time()
        self.hit_count = 0

    def is_valid(self, current_permissions_hash: str, ttl: float = 300.0) -> bool:
        return (
            self.permissions_hash == current_permissions_hash
            and (time.time() - self.cached_at) < ttl
        )

    def record_hit(self) -> None:
        self.hit_count += 1


class AuthorizationCache:
    """Manages cached authorization decisions for registry resolutions.

    When permissions change (e.g., agent roles, handler ACLs, routing policies),
    affected cache entries are invalidated so subsequent resolutions recheck
    authorization against the current policy.
    """

    def __init__(self, default_ttl: float = 300.0):
        self._entries: Dict[str, AuthCacheEntry] = {}
        self._permission_registry: Dict[str, str] = {}
        self._default_ttl = default_ttl
        self._invalidations: int = 0

    def get(self, agent_id: str) -> Optional[AuthCacheEntry]:
        entry = self._entries.get(agent_id)
        if entry is None:
            logger.debug("Auth cache miss for agent %s", agent_id)
            return None

        current_hash = self._permission_registry.get(agent_id, "")
        if not entry.is_valid(current_hash, self._default_ttl):
            logger.info(
                "Auth cache invalidated for agent %s: permissions changed or TTL expired",
                agent_id,
            )
            self._entries.pop(agent_id, None)
            self._invalidations += 1
            return None

        entry.record_hit()
        return entry

    def set(self, agent_id: str, permissions_hash: str, resolver: str) -> AuthCacheEntry:
        entry = AuthCacheEntry(agent_id, permissions_hash, resolver)
        self._entries[agent_id] = entry
        self._permission_registry[agent_id] = permissions_hash
        logger.debug("Auth cache updated for agent %s (resolver=%s)", agent_id, resolver)
        return entry

    def invalidate_for_permission_change(self, agent_id: str) -> bool:
        """Invalidate cache entries for an agent whose permissions changed."""
        old = self._entries.pop(agent_id, None)
        if old is not None:
            self._invalidations += 1
            logger.warning(
                "Auth cache invalidated for agent %s due to permission change "
                "(was resolver=%s, hits=%d)",
                agent_id,
                old.resolver,
                old.hit_count,
            )
            return True
        return False

    def invalidate_all_for_resolver(self, resolver: str) -> int:
        """Invalidate all cache entries associated with a resolver."""
        count = 0
        stale = [aid for aid, entry in self._entries.items() if entry.resolver == resolver]
        for agent_id in stale:
            self._entries.pop(agent_id, None)
            self._invalidations += 1
            count += 1
        if count > 0:
            logger.warning(
                "Auth cache invalidated %d entries for resolver %s",
                count,
                resolver,
            )
        return count

    def invalidate_all(self) -> int:
        """Invalidate the entire authorization cache."""
        count = len(self._entries)
        self._entries.clear()
        self._invalidations += count
        logger.warning("Auth cache fully invalidated (%d entries)", count)
        return count

    def metrics(self) -> Dict[str, Any]:
        return {
            "cache_entries": len(self._entries),
            "invalidations": self._invalidations,
            "default_ttl": self._default_ttl,
        }


class AgentRegistry:
    def __init__(self, storage_backend: str = "memory"):
        self.storage_backend = storage_backend
        self._agents: Dict[str, Dict[str, Any]] = {}
        self._index: Dict[str, List[str]] = {}
        self._auth_cache: AuthorizationCache = AuthorizationCache()

    def register(self, name: str, agent_type: str, config: Optional[Dict] = None) -> str:
        agent_id = str(uuid.uuid4())
        timestamp = time.time()
        permissions_hash = self._compute_permissions_hash(config or {})
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
            "permissions_hash": permissions_hash,
        }
        group = agent_type.split(".")[0]
        if group not in self._index:
            self._index[group] = []
        self._index[group].append(agent_id)

        # Pre-populate auth cache on registration
        resolver = self._resolve_resolver(agent_type)
        self._auth_cache.set(agent_id, permissions_hash, resolver)
        return agent_id

    def get(self, agent_id: str) -> Optional[Dict[str, Any]]:
        agent = self._agents.get(agent_id)
        if agent is None:
            return None

        # Recheck authorization via cache
        cached = self._auth_cache.get(agent_id)
        if cached is None:
            # Cache miss or invalidated — recheck and repopulate
            current_hash = agent.get("permissions_hash", "")
            resolver = self._resolve_resolver(agent.get("type", "unknown"))
            self._auth_cache.set(agent_id, current_hash, resolver)
            logger.info(
                "Authorization rechecked for agent %s (resolver=%s)",
                agent_id,
                resolver,
            )

        return agent

    def resolve(self, agent_id: str, require_authorized: bool = True) -> Optional[Dict[str, Any]]:
        """Resolve an agent with explicit authorization recheck.

        If require_authorized is True, the cached authorization must be valid;
        otherwise a stale or missing cache entry causes a fresh check.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            return None

        if require_authorized:
            current_hash = agent.get("permissions_hash", "")
            resolver = self._resolve_resolver(agent.get("type", "unknown"))
            cached = self._auth_cache.get(agent_id)
            if cached is None:
                self._auth_cache.set(agent_id, current_hash, resolver)
                logger.info(
                    "Authorization rechecked during resolve for agent %s (resolver=%s)",
                    agent_id,
                    resolver,
                )
            elif not cached.is_valid(current_hash, self._auth_cache._default_ttl):
                self._auth_cache.invalidate_for_permission_change(agent_id)
                self._auth_cache.set(agent_id, current_hash, resolver)
                logger.warning(
                    "Stale authorization refreshed during resolve for agent %s",
                    agent_id,
                )

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

        # Permission changes often coincide with status transitions —
        # invalidate auth cache so the next resolve rechecks.
        self._auth_cache.invalidate_for_permission_change(agent_id)
        return True

    def update_permissions(self, agent_id: str, config: Dict[str, Any]) -> bool:
        """Update agent permissions/config, triggering auth cache invalidation."""
        if agent_id not in self._agents:
            return False
        agent = self._agents[agent_id]
        old_hash = agent.get("permissions_hash", "")
        agent["config"].update(config)
        new_hash = self._compute_permissions_hash(agent["config"])
        agent["permissions_hash"] = new_hash
        agent["updated_at"] = time.time()

        if old_hash != new_hash:
            self._auth_cache.invalidate_for_permission_change(agent_id)
            resolver = self._resolve_resolver(agent.get("type", "unknown"))
            self._auth_cache.set(agent_id, new_hash, resolver)
            logger.info(
                "Permissions updated for agent %s (hash: %s -> %s)",
                agent_id,
                old_hash,
                new_hash,
            )
        return True

    def delete(self, agent_id: str) -> bool:
        if agent_id not in self._agents:
            return False
        agent = self._agents.pop(agent_id)
        group = agent["type"].split(".")[0]
        if group in self._index and agent_id in self._index[group]:
            self._index[group].remove(agent_id)
        self._auth_cache.invalidate_for_permission_change(agent_id)
        return True

    def count(self) -> int:
        return len(self._agents)

    def get_auth_cache_metrics(self) -> Dict[str, Any]:
        return self._auth_cache.metrics()

    def invalidate_auth_cache(self, agent_id: Optional[str] = None) -> int:
        """Invalidate auth cache for one agent or all agents."""
        if agent_id:
            return 1 if self._auth_cache.invalidate_for_permission_change(agent_id) else 0
        return self._auth_cache.invalidate_all()

    @staticmethod
    def _compute_permissions_hash(config: Dict[str, Any]) -> str:
        """Deterministic hash of the permission-relevant config."""
        import hashlib
        canonical = json.dumps(config, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode()).hexdigest()[:16]

    @staticmethod
    def _resolve_resolver(agent_type: str) -> str:
        """Map agent type to its resolver name for cache grouping."""
        return agent_type.split(".")[0] if "." in agent_type else agent_type
