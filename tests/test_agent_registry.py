import pytest
import time
from src.agent.registry import AgentRegistry, AgentStatus, AuthorizationCache, AuthCacheEntry


class TestAuthorizationCache:
    def test_cache_hit(self):
        cache = AuthorizationCache(default_ttl=300.0)
        cache.set("agent-1", "hash-v1", "worker")
        entry = cache.get("agent-1")
        assert entry is not None
        assert entry.agent_id == "agent-1"
        assert entry.hit_count == 1

    def test_cache_miss_on_permission_change(self):
        cache = AuthorizationCache(default_ttl=300.0)
        cache.set("agent-1", "hash-v1", "worker")
        # Simulate a permission change by updating the registry
        cache._permission_registry["agent-1"] = "hash-v2"
        entry = cache.get("agent-1")
        assert entry is None  # should be invalidated

    def test_cache_miss_on_ttl_expiry(self):
        cache = AuthorizationCache(default_ttl=0.01)
        cache.set("agent-1", "hash-v1", "worker")
        time.sleep(0.02)
        entry = cache.get("agent-1")
        assert entry is None  # TTL expired

    def test_cache_miss_on_nonexistent(self):
        cache = AuthorizationCache()
        entry = cache.get("nonexistent-id")
        assert entry is None

    def test_cache_invalidate_for_permission_change(self):
        cache = AuthorizationCache()
        cache.set("agent-1", "hash-v1", "worker")
        assert cache.invalidate_for_permission_change("agent-1") is True
        assert cache.get("agent-1") is None

    def test_cache_invalidate_nonexistent(self):
        cache = AuthorizationCache()
        assert cache.invalidate_for_permission_change("nonexistent") is False

    def test_cache_invalidate_all_for_resolver(self):
        cache = AuthorizationCache()
        cache.set("agent-1", "h1", "worker")
        cache.set("agent-2", "h2", "monitor")
        cache.set("agent-3", "h3", "worker")
        assert cache.invalidate_all_for_resolver("worker") == 2
        assert cache.get("agent-1") is None
        assert cache.get("agent-2") is not None  # monitor resolver unaffected
        assert cache.get("agent-3") is None

    def test_cache_invalidate_all(self):
        cache = AuthorizationCache()
        cache.set("agent-1", "h1", "worker")
        cache.set("agent-2", "h2", "monitor")
        assert cache.invalidate_all() == 2
        assert cache.get("agent-1") is None
        assert cache.get("agent-2") is None

    def test_cache_metrics(self):
        cache = AuthorizationCache(default_ttl=60.0)
        cache.set("agent-1", "h1", "worker")
        cache.get("agent-1")  # hit
        cache.invalidate_for_permission_change("agent-1")
        metrics = cache.metrics()
        assert metrics["cache_entries"] == 0
        assert metrics["invalidations"] >= 1
        assert metrics["default_ttl"] == 60.0

    def test_entry_is_valid(self):
        entry = AuthCacheEntry("agent-1", "hash-v1", "worker")
        assert entry.is_valid("hash-v1", 300.0) is True
        assert entry.is_valid("hash-v2", 300.0) is False  # different hash
        # TTL test
        entry.cached_at = time.time() - 400  # 400 seconds ago
        assert entry.is_valid("hash-v1", 300.0) is False  # TTL expired

    def test_entry_record_hit(self):
        entry = AuthCacheEntry("agent-1", "h1", "worker")
        assert entry.hit_count == 0
        entry.record_hit()
        assert entry.hit_count == 1
        entry.record_hit()
        assert entry.hit_count == 2


class TestAgentRegistryAuthCache:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_register_populates_auth_cache(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["cache_entries"] == 1

    def test_get_refreshes_stale_cache(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        # Force cache invalidation
        self.registry.invalidate_auth_cache(agent_id)
        # get() should repopulate cache
        agent = self.registry.get(agent_id)
        assert agent is not None
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["cache_entries"] == 1

    def test_update_status_invalidates_cache(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        assert self.registry.get(agent_id) is not None
        self.registry.update_status(agent_id, AgentStatus.RUNNING)
        # Cache should be invalidated after status change
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["invalidations"] >= 1

    def test_update_permissions_invalidates_cache(self):
        agent_id = self.registry.register("test-agent", "worker.processor", {"role": "viewer"})
        # Cache should be repopulated
        self.registry.update_permissions(agent_id, {"role": "admin"})
        # Cache should have been invalidated and refreshed
        metrics = self.registry.get_auth_cache_metrics()
        # After update_permissions, it invalidates old + sets new
        assert metrics["invalidations"] >= 1

    def test_delete_clears_cache(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        self.registry.delete(agent_id)
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["cache_entries"] == 0

    def test_invalidate_auth_cache_all(self):
        id1 = self.registry.register("agent-1", "worker.processor")
        id2 = self.registry.register("agent-2", "monitor.watcher")
        assert self.registry.invalidate_auth_cache() == 2
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["cache_entries"] == 0

    def test_invalidate_auth_cache_single(self):
        id1 = self.registry.register("agent-1", "worker.processor")
        id2 = self.registry.register("agent-2", "monitor.watcher")
        assert self.registry.invalidate_auth_cache(id1) == 1
        metrics = self.registry.get_auth_cache_metrics()
        assert metrics["cache_entries"] == 1

    def test_resolve_rechecks_authorization(self):
        agent_id = self.registry.register("test-agent", "worker.processor")
        agent = self.registry.resolve(agent_id)
        assert agent is not None

    def test_resolve_nonexistent(self):
        assert self.registry.resolve("nonexistent") is None

    def test_cache_metrics_after_operations(self):
        metrics = self.registry.get_auth_cache_metrics()
        assert "cache_entries" in metrics
        assert "invalidations" in metrics
        assert "default_ttl" in metrics
